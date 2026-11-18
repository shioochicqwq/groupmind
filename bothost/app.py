"""Wiring: one listener for the protocol side (/ws) and the harnesses (/mcp), one worker per group."""
from __future__ import annotations

import asyncio
import contextvars
import hmac
import json
import logging
import os
import re
import secrets
import socket
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import uvicorn
from starlette.responses import PlainTextResponse
from starlette.routing import WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from . import colouring, handoff, lookup, people, sessions, stickers, tools, watch, web
from .config import REPO, Config
from .harness import Dsh, HarnessError, TurnTimeout
from .onebot import Connection, Msg, SendUnknown, parse_group_message
from .store import TZ, Store, line, stamp

log = logging.getLogger("bothost")


CALLER: contextvars.ContextVar["Group | None"] = contextvars.ContextVar("caller", default=None)
NO_USAGE = {"calls": 0, "prompt": 0, "completion": 0}


WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def number_pictures(m: Msg, numbered: dict) -> str:
    """The message text with the pictures given to the model numbered: [图片] -> [图片3]. Later ones first, so the
    positions of earlier ones do not move."""
    out = m.text
    for tag, _, j in sorted(m.images, key=lambda p: -p[2]):
        if (id(m), tag, j) in numbered:
            out = replace_nth(out, f"[{tag}]", f"[{tag}{numbered[(id(m), tag, j)]}]", j)
    return out


def replace_nth(text: str, old: str, new: str, n: int) -> str:
    """Replace the n-th (0-based) remaining occurrence of `old`."""
    start = 0
    for _ in range(n + 1):
        i = text.find(old, start)
        if i < 0:
            return text
        if _ == n:
            return text[:i] + new + text[i + len(old):]
        start = i + len(old)
    return text


def fetch_picture(url: str, limit: int, ffmpeg: str) -> tuple[str, str] | None:
    """(base64, media type) of a picture, an animated one as its first frame in PNG (the model takes no GIF). None on failure."""
    import base64
    import subprocess
    import urllib.request
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=6) as r:
            data = r.read(limit + 1)
    except (OSError, ValueError):
        return None
    if not data or len(data) > limit:
        return None
    kinds = {b"\x89PNG": "image/png", b"\xff\xd8\xff": "image/jpeg", b"RIFF": "image/webp", b"GIF8": "image/gif"}
    mime = next((v for k, v in kinds.items() if data.startswith(k)), "")
    if mime == "image/gif" or not mime:
        try:
            data = subprocess.run([ffmpeg or "ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-frames:v", "1", "-f", "image2pipe",
                                   "-vcodec", "png", "pipe:1"], input=data, capture_output=True, timeout=20, check=True).stdout
            mime = "image/png"
        except (OSError, subprocess.SubprocessError):
            return None
    return base64.b64encode(data).decode(), mime


def split_people(snapshot: str) -> tuple[str, str]:
    """(the "## 人物" section, the rest) of a memory snapshot."""
    m = re.search(r"^## 人物\n.*?(?=^## |\Z)", snapshot, re.S | re.M)
    return (m.group(0), snapshot[:m.start()] + snapshot[m.end():]) if m else ("", snapshot)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@dataclass
class Turn:
    """One turn of one session: what its tools did and, once it has handed the group over, its background task."""
    session: str
    origin: handoff.Origin | None = None   # the message that called the bot in this batch
    sends: int = 0
    lookups: list = field(default_factory=list)
    videos: list = field(default_factory=list)
    task: str = ""                          # set when this turn goes on in the background
    people_upto: int = 0                    # newest person fact this turn's input carries
    pictures: list = field(default_factory=list)   # (number, message id, which picture in it, kind, url) given to the model
    released: asyncio.Event = field(default_factory=asyncio.Event)


class Group:
    """One group: its own harness process, workspace, queue and worker, so groups never wait for each other."""

    def __init__(self, host: "Host", group_id: str, alias: str, system: str) -> None:
        cfg = host.cfg
        self.host, self.group_id, self.alias = host, group_id, alias
        self.token = secrets.token_urlsafe(24)   # tells the tool endpoint which group's harness is calling; new each run
        env = {"DSH_SYSTEM_PROMPT": system, "QQBOT_LLM_API_KEY": cfg.llm_api_key, "QQBOT_LLM_BASE_URL": cfg.llm_base_url,
               "QQBOT_LLM_MODEL": cfg.model, "QQBOT_MCP_URL": cfg.mcp_url, "QQBOT_MCP_TOKEN": self.token,
               "QQBOT_LLM_IMAGES": "1" if cfg.llm_images else "0"}
        # the host plugin's loopback port and the token that has to come with each request (deploy/dsh/handoff.mjs)
        env["QQBOT_HANDOFF_PORT"], env["QQBOT_HANDOFF_TOKEN"] = str(free_port()), secrets.token_urlsafe(24)
        if cfg.handoff:   # the plugin also owns the sessions, and a slow call may take as long as it needs
            env["QQBOT_PLUGIN_SESSIONS"] = "1"
            env["QQBOT_TOOL_TIMEOUT_MS"] = str(int(cfg.handoff_tool_timeout_s * 1000))
        self.dsh = Dsh(cfg.dsh_cmd, host.patches, cfg.data_dir / "dsh-home", cfg.data_dir / "workspace" / alias, env, "bot", cfg.model)
        self.pending: list[Msg] = []
        self.due: float | None = None
        self.wake = asyncio.Event()
        self.origin: Msg | None = None          # the newest message that called the bot, not answered yet
        self.current: Turn | None = None        # the turn of the session that has the group
        self.turns: dict[str, Turn] = {}        # session -> its running turn (the current one and those in the background)
        self.last_session: str | None = None
        self.people_upto = 0          # newest person fact this group's session has been shown (in the table or appended)
        self.people_set = (-1, "")    # (process start, session) the people table was last set for
        self.sticker_notes: list[str] = []   # what stickers meant, for the next turn when the message was read already

    def add(self, msg: Msg, called: bool) -> None:
        self.pending.append(msg)
        del self.pending[:-self.host.cfg.pending_cap]
        if called:
            self.origin = msg
        if called and self.due is None:
            self.due = time.monotonic() + self.host.cfg.debounce_s
            self.wake.set()

    async def worker(self) -> None:
        cfg = self.host.cfg
        while True:
            if self.due is None:
                self.wake.clear()
                try:
                    await asyncio.wait_for(self.wake.wait(), cfg.idle_stop_s)
                except asyncio.TimeoutError:
                    if not self.turns:   # background tasks run in the same process
                        await self.dsh.stop()
                continue
            await asyncio.sleep(max(0.0, self.due - time.monotonic()))
            self.due = None
            batch, self.pending = self.pending, []
            if batch:
                async with self.host.slots:
                    await self.run_turn(batch)

    async def run_turn(self, batch: list[Msg]) -> None:
        cfg, ho = self.host.cfg, self.host.handoff
        base = f"{self.alias}-{time.strftime('%Y%m%d', time.localtime(batch[-1].ts))}" if cfg.daily_session else self.alias
        session = ho.active(self.alias, base) if ho else base
        if ho and self.last_session not in (None, session) and self.last_session not in self.turns:
            await self.dsh.close(self.last_session)   # a new day's session took over and the old one is idle
        self.last_session = session
        # Every line carries its time; the year and the weekday are said once per turn.
        now = batch[-1].ts   # the newest message: the turn starts a moment after it
        # pictures go to the model with the turn; stickers are seen apart (Host.see_stickers) and arrive as text
        pictures = [(m, j, tag, url) for m in batch for tag, url, j in m.images if tag == "图片"][: cfg.max_images_per_turn if cfg.llm_images else 0]
        numbered = {(id(m), tag, j): n for n, (m, j, tag, _) in enumerate(pictures, 1)}
        text = f"（现在 {stamp(now)} {WEEKDAYS[datetime.fromtimestamp(now, TZ).weekday()]}）\n" \
               + "\n".join(line(m.ts, m.name, number_pictures(m, numbered)) for m in batch)
        notes, upto = ho.notes(self.alias) if ho else ([], 0)
        notes, self.sticker_notes = notes + self.sticker_notes, []
        if notes:   # what background sessions did, in the order it was recorded; never inserted into a running request
            text = "（内部记录，不是群消息）\n" + "\n".join(notes) + "\n\n" + text
        asked = self.origin if self.origin in batch else batch[-1]
        self.origin = None
        turn = self.current = self.turns[session] = Turn(session, handoff.Origin(asked.msg_id, asked.ts, asked.name, asked.text))
        turn.pictures = [(n, m.msg_id, j, tag, url, m.name) for n, (m, j, tag, url) in enumerate(pictures, 1)]
        t0, started = time.monotonic(), time.strftime("%Y-%m-%d %H:%M:%S")
        job = asyncio.create_task(self._drive(turn, text, batch[0].ts))
        if ho:   # no time limit: the turn ends, hands the group over, or is cancelled for standing still
            released = asyncio.create_task(turn.released.wait())
            await asyncio.wait({job, released}, return_when=asyncio.FIRST_COMPLETED)
            released.cancel()
            if turn.released.is_set():   # the group has a new session; this turn finishes in the background
                self.current = None
                if upto:
                    ho.delivered(self.alias, upto)
                self.people_upto = max(self.people_upto, turn.people_upto)   # the new session was copied from this turn's input
                asyncio.create_task(self._background(turn, job, t0, started, len(batch)))
                return
        usage, new = await job
        self.current = None
        self.turns.pop(session, None)
        if ho and upto and usage.get("calls"):   # the model has read them
            ho.delivered(self.alias, upto)
        if usage.get("calls"):
            self.people_upto = max(self.people_upto, turn.people_upto)
        self._record(turn, usage, new, started, t0, len(batch))

    async def _drive(self, turn: Turn, text: str, first_ts: float) -> tuple[dict, bool]:
        """Open the session and run one turn. (usage, whether the session was new)."""
        new = False
        try:
            new = await self.dsh.open(turn.session)
            if self.people_set != (self.dsh.starts, turn.session) or new:   # a new process or session: no warm prefix to keep
                await self.refresh_people(turn.session)
            learned, turn.people_upto = people.changed_since(self.host.store.db, self.people_upto)
            if learned:   # people learned since the table was set: appended here, the system prompt stays as it was
                text = people.block(learned) + "\n\n" + text
            if new:
                recap = self.host.store.recent(self.alias, self.host.cfg.recap_lines, first_ts)
                if recap:
                    text = ("（之前的聊天，供参考）\n" + "\n".join(line(r["ts"], r["name"] or "?", r["text"]) for r in recap)
                            + "\n\n（新消息）\n" + text)
            self.dsh.last_text.pop(turn.session, None)
            got = await asyncio.gather(*(asyncio.to_thread(fetch_picture, url, self.host.cfg.max_image_bytes, self.host.cfg.ffmpeg)
                                         for _, _, _, _, url, _ in turn.pictures))   # side by side: one slow picture does not add up
            images = [(f"{tag}{n}（{name}发的）：", *g) for (n, _, _, tag, _, name), g in zip(turn.pictures, got) if g]
            if turn.pictures and len(images) < len(turn.pictures):
                text += f"\n（有 {len(turn.pictures) - len(images)} 张图没取到，看不到内容。）"
            if self.host.handoff:
                usage = await self.dsh.turn(turn.session, text, stall=self.host.cfg.stall_s, images=images)
            else:
                usage = await self.dsh.turn(turn.session, text, self.host.cfg.turn_timeout_s, images=images)
            self.describe_pictures(turn)
        except TurnTimeout as e:
            usage = {**e.usage, "error": "timeout"}
            if not self.host.handoff:   # without handoff the process is the only way to stop a turn
                await self.dsh.kill()   # it may still be working on this turn; do not let it speak into a later one
        except (HarnessError, asyncio.TimeoutError) as e:
            usage = {**NO_USAGE, "error": str(e)[:80] or type(e).__name__}
        return usage, new

    async def _background(self, turn: Turn, job: asyncio.Task, t0: float, started: str, lines: int) -> None:
        """Wait for a turn that handed the group over; then its one reply (quoting the message that asked) and its account."""
        ho = self.host.handoff
        usage, new = await job
        if "error" in usage:
            ho.finish(turn.task, False, error="停住不动，取消了" if usage["error"] == "stalled" else f"出错了（{usage['error']}）")
        elif ho.running(turn.task):
            reply, summary = handoff.parse_wrap_up(self.dsh.last_text.get(turn.session, ""))
            if isinstance(summary.get("people"), list):   # people it got to know while doing the task
                people.apply(self.host.store.db, [u for u in summary["people"] if isinstance(u, dict)], "handoff", self.alias, f"task {turn.task}")
            sent = bool(reply) and await self.host.post(self, reply, turn.origin.msg_id if turn.origin else "") in ("ok", "unknown")
            ho.finish(turn.task, True, reply, summary, sent=sent)
            turn.sends += sent
        self.turns.pop(turn.session, None)
        try:   # retired: out of memory; its log stays on disk
            await self.dsh.close(turn.session)
        except HarnessError as e:
            log.warning("could not close %s: %s", turn.session, e)
        self._record(turn, usage, new, started, t0, lines)

    def describe_pictures(self, turn: Turn) -> None:
        """Keep what the model saw in each picture with the message, marked as seen by the machine, so recall finds it.
        The model writes them as 【图片N】… lines after its reply (bothost/prompt.md)."""
        said = self.dsh.last_text.get(turn.session, "")
        for n, msg_id, j, tag, _, _ in sorted(turn.pictures, key=lambda p: -p[2]):   # later ones first: earlier positions stay put
            m = re.search(rf"【{tag}{n}】\s*(.+)", said)
            if not m:
                continue
            row = self.host.store.db.execute("SELECT text FROM message WHERE source = ? AND source_msg_id = ?",
                                             (f"{self.host.store.platform}:{self.alias}", f"ob:{msg_id}")).fetchone()
            if row:
                desc = m.group(1).strip().rstrip("。")[:120]
                self.host.store.retext(self.alias, msg_id, replace_nth(row[0], f"[{tag}]", f"[{tag}：{desc}（机器看的）]", j))

    async def refresh_people(self, session: str) -> None:
        """Rebuild the people table in the system prompt, taking in everything appended since. Only when the cached prefix is
        lost anyway: a new process, a new session, a compaction."""
        upto = people.latest_id(self.host.store.db)
        try:
            await self.dsh.plugin("set_people", text=self.host.people_table())
        except HarnessError as e:   # appended blocks still carry what is new
            log.warning("people table not set in %s: %s", self.alias, e)
            return
        self.people_upto, self.people_set = upto, (self.dsh.starts, session)

    def _record(self, turn: Turn, usage: dict, new: bool, started: str, t0: float, lines: int) -> None:
        cfg = self.host.cfg
        for note in self.dsh.notes_written.pop(turn.session, []):   # the compaction note may end with a 【人物】 section
            got = people.apply(self.host.store.db, people.parse_section(note), "compaction", self.alias, "compaction note")
            if got["recorded"] or got["unknown"]:
                log.info("people from a compaction note in %s: %d recorded, %d names not found", self.alias, got["recorded"], len(got["unknown"]))
        row = {"started": started, "group": self.alias, "session": turn.session, "model": cfg.model, "lines": lines,
               "sent": turn.sends, "seconds": round(time.monotonic() - t0, 1), **usage}
        if turn.task:
            row["task"] = turn.task
        if turn.lookups:   # the helper's own model calls, apart from the session's
            row["lookup"] = {k: round(sum(u.get(k, 0) for u in turn.lookups), 1) for k in ("calls", "prompt", "cached", "completion", "web_calls", "seconds")}
            row["lookup"]["times"] = len(turn.lookups)
        if turn.videos:   # the video model's calls
            row["video"] = {k: round(sum(u.get(k, 0) for u in turn.videos), 1) for k in ("calls", "prompt", "completion", "seconds")}
        why = ["cold_start"] * new + ["compaction"] * bool(usage.get("compactions"))
        if usage.get("compactions") and not turn.task:   # the prefix was rebuilt anyway: fold the appended people into the table
            asyncio.create_task(self.refresh_people(turn.session))
        if why:
            row["reset"], row["uncoloured"] = "+".join(why), self.host.context_reset(self.alias, why)
        with open(cfg.data_dir / "usage.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        log.info("turn %s%s: %d lines in, %d sent, %d model calls, %.1fs%s", self.alias, " (background)" if turn.task else "", lines,
                 turn.sends, usage["calls"], row["seconds"], f", ended on error {usage['error']}" if "error" in usage else "")


class Host:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.store = Store(cfg.db_file)
        self.lookups: lookup.Lookups | None = None   # made at the first look-up
        self.stickers = stickers.Stickers(cfg.data_dir / "stickers.json", cfg.sticker_model or cfg.model,
                                          cfg.sticker_base_url or cfg.llm_base_url, cfg.sticker_api_key) if cfg.stickers else None
        self.colouring = colouring.Colouring(cfg.db_file, cfg.colour_model, cfg.colour_base_url or cfg.llm_base_url, cfg.colour_api_key,
                                             cfg.data_dir / "usage.jsonl") if cfg.colour_model else None
        self.watcher = watch.Watcher(wait=None if cfg.handoff else watch.WAIT_S, model=cfg.video_model, base_url=cfg.video_base_url, api_key=cfg.video_api_key,
                                     ffmpeg=cfg.ffmpeg, ytdlp=cfg.ytdlp) if cfg.video_model else None
        # The harness's own compaction is replaced by one where the bot writes the note. Written first, so a patch from the
        # config can still change it. If the plugin fails to load there is no compaction at all: see dsh.stderr.log.
        window = int(os.environ.get("QQBOT_LLM_CONTEXT", 262144))
        patch = cfg.data_dir / "compaction.patch.yml"
        patch.write_text(json.dumps([{"id": "compaction-basic", "disabled": True}, {"insert": [{
            "id": "compaction-persona", "name": str(REPO / "deploy" / "dsh" / "compaction-persona.mjs"),
            "config": {"thresholdRatio": min(1.0, cfg.compact_at_tokens / window), "retainTokens": cfg.compact_keep_tokens, "maxTokens": 8000}}]}]),
            encoding="utf-8")   # JSON is YAML
        self.patches = [str(patch), *cfg.dsh_patches]
        plugin = cfg.data_dir / "handoff.patch.yml"   # the host plugin: people table, and sessions with handoff
        plugin.write_text(json.dumps([{"insert": [{"id": "qq-handoff", "name": str(REPO / "deploy" / "dsh" / "handoff.mjs"),
                                                   "config": {"provider": "bot", "model": cfg.model}}]}]), encoding="utf-8")
        self.patches.append(str(plugin))
        self.handoff: handoff.Handoff | None = None
        if cfg.handoff:
            self.handoff = handoff.Handoff(cfg.data_dir / "handoff.db", cfg.handoff_max_tasks, cfg.handoff_max_total)
            if cut := self.handoff.recover():
                log.info("%d background tasks were cut off by the last stop", cut)
        # Persona, then the group rules, then the snapshot. Fixed for the life of the process: the prefix stays cacheable.
        here = Path(__file__).parent
        parts = [Path(cfg.persona_file).read_text(encoding="utf-8")] if cfg.persona_file else []
        parts.append((here / "prompt.md").read_text(encoding="utf-8").replace("{name}", cfg.bot_names[0])
                     .replace("{max_sends}", str(cfg.max_sends_per_turn)))
        if cfg.search_api_key:
            parts.append((here / "prompt_web.md").read_text(encoding="utf-8"))
        if cfg.video_model:
            parts.append((here / "prompt_video.md").read_text(encoding="utf-8"))
        # The snapshot's people section is not part of this fixed text: it goes into the people table, a section of the system
        # prompt the host rebuilds when the cached prefix is lost anyway (Group.refresh_people). The rest stays fixed here.
        self.labelled_people = ""
        if cfg.snapshot_file:
            snap = Path(cfg.snapshot_file).read_text(encoding="utf-8")
            self.labelled_people, rest = split_people(snap)
            parts.append(rest)
        system = "\n\n".join(x.strip() for x in parts)
        self.groups = {gid: Group(self, gid, alias, system) for gid, alias in cfg.groups.items()}
        self.by_token = {g.token: g for g in self.groups.values()}
        self.slots = asyncio.Semaphore(cfg.max_parallel_turns)
        self.conn: Connection | None = None
        self.self_id = ""

    def people_table(self) -> str:
        """The people the bot knows: the labelled ones from the snapshot, then those it got to know by itself."""
        return "\n\n".join(x for x in (self.labelled_people.strip(), people.learned_section(self.store.db)) if x)

    def context_reset(self, alias: str, why: list[str]) -> int:
        """The one place that hears a group's session lost context: a new session started, or the harness replaced
        the oldest part with a summary. Earlier talk is no longer in front of the model in full, so this is when the
        messages not coloured yet are due. Colouring reads them from the store, so nothing has to be handed over.
        With a colour model set it starts in the background (bothost/colouring.py); either way the count is reported."""
        waiting = self.store.uncoloured(alias)
        log.info("context reset in %s (%s): %d messages not coloured yet", alias, "+".join(why), waiting)
        if self.colouring is not None and waiting:
            asyncio.create_task(self.colouring.start(alias, why))
        return waiting

    # ---- protocol side ----
    async def ws(self, sock: WebSocket) -> None:
        given = sock.headers.get("authorization", "").removeprefix("Bearer ").strip() or sock.query_params.get("access_token", "")
        if not hmac.compare_digest(given, self.cfg.onebot_token):
            await sock.close(code=1008)
            return
        await sock.accept()
        # A replay connection only feeds events in again (e.g. a message from before a fix, fetched from the protocol side
        # with get_msg); it does not take over the protocol side's connection, so sending keeps going through that one.
        replay = sock.headers.get("x-qqbot-replay") == "1"
        conn = Connection(sock.send_text)
        if not replay:
            self.conn = conn
        self.self_id = sock.headers.get("x-self-id", self.self_id)
        log.info("protocol side connected")
        try:
            while True:
                frame = json.loads(await sock.receive_text())
                if not conn.feed(frame):
                    self.on_event(frame, replay)
        except WebSocketDisconnect:
            log.info("protocol side disconnected")
        finally:
            conn.close()
            if self.conn is conn:
                self.conn = None

    def on_event(self, ev: dict, replay: bool = False) -> None:
        gid = str(ev.get("group_id", ""))
        alias = self.groups[gid].alias if gid in self.groups else ""
        msg = parse_group_message(ev, lambda uid: self.store.shown_name(alias, uid))
        grp = self.groups.get(msg.group_id) if msg else None
        if msg is None or grp is None or not msg.text and not msg.at_me:
            return
        self.self_id = self.self_id or str(ev.get("self_id", ""))
        if msg.user_id == self.self_id:
            return
        called = msg.at_me or self.store.is_from(grp.alias, msg.reply_to, self.self_id) or any(n in msg.text for n in self.cfg.bot_names)
        called = called or self.cfg.shadow   # shadow test: the bot never speaks, so nobody calls it; every message is a chance
        if msg.at_me:
            msg.text = f"@{self.cfg.bot_names[0]} {msg.text}".strip()
        self.store.add(grp.alias, msg.msg_id, msg.ts, msg.user_id, msg.name, msg.text, msg.reply_to)
        if replay:   # stored before, perhaps read worse: keep the text as it is read now
            self.store.retext(grp.alias, msg.msg_id, msg.text)
        grp.add(msg, called)
        if self.stickers and any(tag == "表情" for tag, _, _ in msg.images):
            asyncio.create_task(self.see_stickers(grp, msg))

    async def see_stickers(self, grp: Group, msg: Msg) -> None:
        """What the stickers in a message mean, seen by a call of their own. The session gets it in the message when it has
        not read it yet, otherwise as a line of its next turn; the store keeps it with the message."""
        cfg, said = self.cfg, []
        for tag, url, j in sorted((p for p in msg.images if p[0] == "表情"), key=lambda p: -p[2]):   # later ones first
            picture = await asyncio.to_thread(fetch_picture, url, cfg.max_image_bytes, cfg.ffmpeg)
            meaning = await self.stickers.meaning(picture) if picture else ""
            if not meaning:
                continue
            label = f"[表情：{meaning}（机器看的）]"
            row = self.store.db.execute("SELECT text FROM message WHERE source = ? AND source_msg_id = ?",
                                        (f"{self.store.platform}:{grp.alias}", f"ob:{msg.msg_id}")).fetchone()
            if row:
                self.store.retext(grp.alias, msg.msg_id, replace_nth(row[0], "[表情]", label, j))
            if any(m is msg for m in grp.pending):   # not read yet: the session sees it in the message itself
                msg.text = replace_nth(msg.text, "[表情]", label, j)
            else:
                said.append(meaning)
        if said:
            grp.sticker_notes.append(f"[{stamp(msg.ts, '%m-%d %H:%M')}] {msg.name} 刚才发的表情：{'；'.join(reversed(said))}")
        if self.stickers.used:
            used, self.stickers.used = self.stickers.used, []
            with open(cfg.data_dir / "usage.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps({"started": time.strftime("%Y-%m-%d %H:%M:%S"), "group": grp.alias, "model": self.stickers.model,
                                    "sticker": {k: round(sum(u[k] for u in used), 1) for k in ("calls", "prompt", "completion", "seconds")}},
                                   ensure_ascii=False) + "\n")

    # ---- tools (called by a group's harness through MCP; CALLER says which group) ----
    async def turn_of(self, grp: Group, tool: str, given: dict) -> tuple[Turn | None, str]:
        """The turn a tool call belongs to and the call's id (empty without handoff, where only the current turn can call)."""
        if self.handoff is None:
            return grp.current, ""
        found = await grp.dsh.find_call(f"mcp__qq__{tool}", given)
        if found and found[0] in grp.turns:
            return grp.turns[found[0]], found[1]
        return grp.current, ""

    async def send(self, text: str) -> str:
        grp, text = CALLER.get(), text.strip()
        turn = (await self.turn_of(grp, "send_group_message", {"text": text}))[0] if grp else None
        if turn is None:
            return "现在没有进行中的对话，不能发送。"
        if turn.task:   # the reply gate: a session in the background speaks once, through its task, quoting the message
            return "群聊已经由你的另一个会话接着聊了，这里不能直接发言。把要说的写在正文的【回复】里。"
        if not text:
            return "内容为空，没有发送。"
        if turn.sends >= self.cfg.max_sends_per_turn:
            return "这一轮已经发够了，没有发送。结束这一轮。"
        if self.conn is None and not self.cfg.shadow:
            return "QQ 没连上，没有发送。不要重试。"
        turn.sends += 1
        how = await self.post(grp, text)
        if how == "ok":
            return "已发送。"
        if how == "unknown":
            return "发送状态不明（可能已经发出）。不要重发，结束这一轮。"
        turn.sends -= 1
        return f"发送失败：{how}"

    async def post(self, grp: Group, text: str, reply_to: str = "") -> str:
        """Send one message, quoting `reply_to` when given, and store it. "ok", "unknown" (may have gone out) or the error.
        Shadow test: nothing goes to the group or the store; the line is kept in shadow.jsonl for reading afterwards."""
        if self.cfg.shadow:
            with open(self.cfg.data_dir / "shadow.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": time.time(), "group": grp.alias, "reply_to": reply_to, "text": text[: self.cfg.max_message_chars],
                                    "session": grp.current.session if grp.current else ""}, ensure_ascii=False) + "\n")
            if self.cfg.shadow_forward_to and self.conn is not None:
                await self.forward_shadow(grp, text, reply_to)
            return "ok"
        if self.conn is None:
            return "QQ 没连上"
        text = text[: self.cfg.max_message_chars]
        name = self.cfg.bot_names[0]
        segments = ([{"type": "reply", "data": {"id": reply_to}}] if reply_to else []) + [{"type": "text", "data": {"text": text}}]
        try:
            data = await self.conn.call("send_group_msg", {"group_id": int(grp.group_id), "message": segments}, self.cfg.send_timeout_s)
        except SendUnknown:
            self.store.add(grp.alias, "", time.time(), self.self_id or "self", name, text, reply_to)
            return "unknown"
        except RuntimeError as e:
            return str(e)
        self.store.add(grp.alias, str(data.get("message_id", "")), time.time(), self.self_id or "self", name, text, reply_to)
        return "ok"

    async def forward_shadow(self, grp: Group, text: str, reply_to: str) -> None:
        """Shadow test: show the line the bot would have said to one person, privately, with the group lines just before it.
        Not stored; a failure here does not touch the test."""
        recent = self.store.recent(grp.alias, self.cfg.shadow_context_lines)
        quoted = ""
        if reply_to:
            row = self.store.db.execute("SELECT m.nickname_at_time, m.text FROM message m WHERE m.source = ? AND m.source_msg_id = ?",
                                        (f"{self.store.platform}:{grp.alias}", f"ob:{reply_to}")).fetchone()
            if row:
                quoted = f"\n（引用 {row[0] or '?'}：{row[1][:60]}）"
        body = (f"【影子·{grp.alias}】{text[: self.cfg.max_message_chars]}{quoted}\n—— 群里最近：\n"
                + "\n".join(line(r["ts"], r["name"] or "?", r["text"][:120]) for r in recent))
        try:
            await self.conn.call("send_private_msg", {"user_id": int(self.cfg.shadow_forward_to),
                                                      "message": [{"type": "text", "data": {"text": body[:3000]}}]}, self.cfg.send_timeout_s)
        except (SendUnknown, RuntimeError, ValueError) as e:
            log.warning("shadow forward failed: %s", type(e).__name__)

    async def escalate(self, grp: Group, turn: Turn, call: str, kind: str, detail: str) -> None:
        """The slow part of a call is about to start: hand the group over to a new session, if this turn still has it."""
        if self.handoff is None or turn.task or not call:
            return
        got = await self.handoff.hand_over(grp.alias, turn.session, call, kind, detail[:300], turn.origin,
                                           lambda child: grp.dsh.fork(turn.session, child, call))
        if got:
            turn.task = got[0]
            turn.released.set()
            log.info("handoff in %s: %s -> %s (%s)", grp.alias, turn.session, got[1], kind)

    async def look_up(self, question: str, follow_up: str = "") -> str:
        """Web search and page reading in a conversation of their own; the group's session gets the conclusion and the steps taken."""
        cfg, grp = self.cfg, CALLER.get()
        if self.lookups is None:
            web.use_browser(str(cfg.data_dir / "browser-profile"), cfg.browser_executable, cfg.xvfb_command)
            self.lookups = lookup.Lookups(model=cfg.lookup_model or cfg.model, base_url=cfg.lookup_base_url or cfg.llm_base_url, llm_key=cfg.lookup_api_key,
                                          web_key=cfg.search_api_key,
                                          timeout=cfg.handoff_tool_timeout_s - 30 if cfg.handoff else cfg.lookup_timeout_s)
        turn, call = await self.turn_of(grp, "look_up", {"question": question, "follow_up": follow_up}) if grp else (None, "")
        # page reading calls this just before it starts a browser; the look-up itself goes on either way
        token = web.ESCALATE.set(lambda kind, url: self.escalate(grp, turn, call, kind, url)) if turn and call else None
        try:
            answer, used = await self.lookups.ask(question, follow_up)
        finally:
            if token is not None:
                web.ESCALATE.reset(token)
        if turn is not None:
            turn.lookups.append(used)
            if turn.task:
                answer += handoff.wrap_up(turn.origin)
        return answer

    async def watch_video(self, url: str, question: str, start: float, end: float) -> str:
        grp = CALLER.get()
        turn, call = await self.turn_of(grp, "watch_video", {"url": url, "question": question}) if grp else (None, "")
        if turn is not None:
            await self.escalate(grp, turn, call, "video", url)
        answer, used = await self.watcher.ask(url, question, start, end)
        if turn is not None:
            if used:
                turn.videos.append(used)
            if turn.task:
                answer += handoff.wrap_up(turn.origin)
        return answer

    # ---- serving ----
    def asgi(self):
        cfg = self.cfg
        # what was said one-on-one stays out of the groups
        server = tools.build(self.store, self, lambda: g.alias if (g := CALLER.get()) else "", (*cfg.history_exclude, sessions.CODE),
                             lookup=self.look_up if cfg.search_api_key else None,
                             video=self.watch_video if self.watcher else None)
        app = server.streamable_http_app(streamable_http_path="/mcp", stateless_http=True, json_response=True)
        app.router.routes.append(WebSocketRoute("/ws", self.ws))

        async def guarded(scope, receive, send):
            if scope["type"] == "http":
                given = dict(scope["headers"]).get(b"authorization", b"").decode().removeprefix("Bearer ").strip()
                grp = self.by_token.get(given)
                if grp is None:
                    return await PlainTextResponse("unauthorized", 401)(scope, receive, send)
                CALLER.set(grp)   # each request runs in its own task, so this does not leak between groups
            await app(scope, receive, send)
        return guarded

    async def serve(self) -> None:
        server = uvicorn.Server(uvicorn.Config(self.asgi(), host=self.cfg.listen_host, port=self.cfg.listen_port, log_level="warning",
                                              timeout_graceful_shutdown=3))
        workers = [asyncio.create_task(g.worker()) for g in self.groups.values()]
        try:
            await server.serve()
        finally:
            for w in workers:
                w.cancel()
            await asyncio.gather(*(g.dsh.stop() for g in self.groups.values()))
