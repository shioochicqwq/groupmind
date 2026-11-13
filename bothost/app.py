"""Wiring: one listener for the protocol side (/ws) and the harnesses (/mcp), one worker per group."""
from __future__ import annotations

import asyncio
import contextvars
import hmac
import json
import logging
import os
import secrets
import time
from pathlib import Path

import uvicorn
from starlette.responses import PlainTextResponse
from starlette.routing import WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from . import lookup, tools
from .config import REPO, Config
from .harness import Dsh, HarnessError, TurnTimeout
from .onebot import Connection, Msg, SendUnknown, parse_group_message
from .store import Store, line

log = logging.getLogger("bothost")


CALLER: contextvars.ContextVar["Group | None"] = contextvars.ContextVar("caller", default=None)
NO_USAGE = {"calls": 0, "prompt": 0, "completion": 0}


class Group:
    """One group: its own harness process, workspace, queue and worker, so groups never wait for each other."""

    def __init__(self, host: "Host", group_id: str, alias: str, system: str) -> None:
        cfg = host.cfg
        self.host, self.group_id, self.alias = host, group_id, alias
        self.token = secrets.token_urlsafe(24)   # tells the tool endpoint which group's harness is calling; new each run
        self.dsh = Dsh(cfg.dsh_cmd, host.patches, cfg.data_dir / "dsh-home", cfg.data_dir / "workspace" / alias, {
            "DSH_SYSTEM_PROMPT": system, "QQBOT_LLM_API_KEY": cfg.llm_api_key, "QQBOT_LLM_BASE_URL": cfg.llm_base_url,
            "QQBOT_LLM_MODEL": cfg.model, "QQBOT_MCP_URL": cfg.mcp_url, "QQBOT_MCP_TOKEN": self.token}, "bot", cfg.model)
        self.pending: list[Msg] = []
        self.due: float | None = None
        self.wake = asyncio.Event()
        self.in_turn = False
        self.sends, self.lookups = 0, []

    def add(self, msg: Msg, called: bool) -> None:
        self.pending.append(msg)
        del self.pending[:-self.host.cfg.pending_cap]
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
                    await self.dsh.stop()
                continue
            await asyncio.sleep(max(0.0, self.due - time.monotonic()))
            self.due = None
            batch, self.pending = self.pending, []
            if batch:
                async with self.host.slots:
                    await self.run_turn(batch)

    async def run_turn(self, batch: list[Msg]) -> None:
        cfg, store = self.host.cfg, self.host.store
        session = f"{self.alias}-{time.strftime('%Y%m%d', time.localtime(batch[-1].ts))}" if cfg.daily_session else self.alias
        text = "\n".join(line(m.ts, m.name, m.text) for m in batch)
        self.in_turn, self.sends, self.lookups = True, 0, []
        t0, started, new = time.monotonic(), time.strftime("%Y-%m-%d %H:%M:%S"), False
        try:
            new = await self.dsh.open(session)
            if new:
                recap = store.recent(self.alias, cfg.recap_lines, batch[0].ts)
                if recap:
                    text = ("（之前的聊天，供参考）\n" + "\n".join(line(r["ts"], r["name"] or "?", r["text"]) for r in recap)
                            + "\n\n（新消息）\n" + text)
            usage = await self.dsh.turn(session, text, cfg.turn_timeout_s)
        except TurnTimeout as e:
            usage = {**e.usage, "error": "timeout"}
            await self.dsh.kill()   # it may still be working on this turn; do not let it speak into a later one
        except (HarnessError, asyncio.TimeoutError) as e:
            usage = {**NO_USAGE, "error": str(e)[:80] or type(e).__name__}
        finally:
            self.in_turn = False
        row = {"started": started, "group": self.alias, "session": session, "model": cfg.model, "lines": len(batch),
               "sent": self.sends, "seconds": round(time.monotonic() - t0, 1), **usage}
        if self.lookups:   # the helper's own model calls, apart from the session's
            row["lookup"] = {k: round(sum(u.get(k, 0) for u in self.lookups), 1) for k in ("calls", "prompt", "cached", "completion", "web_calls", "seconds")}
            row["lookup"]["times"] = len(self.lookups)
        why = ["cold_start"] * new + ["compaction"] * bool(usage.get("compactions"))
        if why:
            row["reset"], row["uncoloured"] = "+".join(why), self.host.context_reset(self.alias, why)
        with open(cfg.data_dir / "usage.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        log.info("turn %s: %d lines in, %d sent, %d model calls, %.1fs%s", self.alias, len(batch), self.sends, usage["calls"],
                 row["seconds"], f", ended on error {usage['error']}" if "error" in usage else "")


class Host:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.store = Store(cfg.db_file)
        # The harness's own compaction is replaced by one where the bot writes the note. Written first, so a patch from the
        # config can still change it. If the plugin fails to load there is no compaction at all: see dsh.stderr.log.
        window = int(os.environ.get("QQBOT_LLM_CONTEXT", 262144))
        patch = cfg.data_dir / "compaction.patch.yml"
        patch.write_text(json.dumps([{"id": "compaction-basic", "disabled": True}, {"insert": [{
            "id": "compaction-persona", "name": str(REPO / "deploy" / "dsh" / "compaction-persona.mjs"),
            "config": {"thresholdRatio": cfg.compact_at_tokens / window, "retainTokens": cfg.compact_keep_tokens, "maxTokens": 8000}}]}]),
            encoding="utf-8")   # JSON is YAML
        self.patches = [str(patch), *cfg.dsh_patches]
        # Persona, then the group rules, then the snapshot. Fixed for the life of the process: the prefix stays cacheable.
        here = Path(__file__).parent
        parts = [Path(cfg.persona_file).read_text(encoding="utf-8")] if cfg.persona_file else []
        parts.append((here / "prompt.md").read_text(encoding="utf-8").replace("{name}", cfg.bot_names[0])
                     .replace("{max_sends}", str(cfg.max_sends_per_turn)))
        if cfg.search_api_key:
            parts.append((here / "prompt_web.md").read_text(encoding="utf-8"))
        if cfg.snapshot_file:
            parts.append(Path(cfg.snapshot_file).read_text(encoding="utf-8"))
        system = "\n\n".join(x.strip() for x in parts)
        self.groups = {gid: Group(self, gid, alias, system) for gid, alias in cfg.groups.items()}
        self.by_token = {g.token: g for g in self.groups.values()}
        self.slots = asyncio.Semaphore(cfg.max_parallel_turns)
        self.conn: Connection | None = None
        self.self_id = ""

    def context_reset(self, alias: str, why: list[str]) -> int:
        """The one place that hears a group's session lost context: a new session started, or the harness replaced
        the oldest part with a summary. Earlier talk is no longer in front of the model in full, so this is when the
        messages not coloured yet are due. Colouring reads them from the store, so nothing has to be handed over.
        The colouring job itself is not attached yet; for now this reports how many messages are waiting."""
        waiting = self.store.uncoloured(alias)
        log.info("context reset in %s (%s): %d messages not coloured yet", alias, "+".join(why), waiting)
        return waiting

    # ---- protocol side ----
    async def ws(self, sock: WebSocket) -> None:
        given = sock.headers.get("authorization", "").removeprefix("Bearer ").strip() or sock.query_params.get("access_token", "")
        if not hmac.compare_digest(given, self.cfg.onebot_token):
            await sock.close(code=1008)
            return
        await sock.accept()
        conn = self.conn = Connection(sock.send_text)
        self.self_id = sock.headers.get("x-self-id", self.self_id)
        log.info("protocol side connected")
        try:
            while True:
                frame = json.loads(await sock.receive_text())
                if not conn.feed(frame):
                    self.on_event(frame)
        except WebSocketDisconnect:
            log.info("protocol side disconnected")
        finally:
            conn.close()
            if self.conn is conn:
                self.conn = None

    def on_event(self, ev: dict) -> None:
        msg = parse_group_message(ev)
        grp = self.groups.get(msg.group_id) if msg else None
        if msg is None or grp is None or not msg.text and not msg.at_me:
            return
        self.self_id = self.self_id or str(ev.get("self_id", ""))
        if msg.user_id == self.self_id:
            return
        called = msg.at_me or self.store.is_from(grp.alias, msg.reply_to, self.self_id) or any(n in msg.text for n in self.cfg.bot_names)
        if msg.at_me:
            msg.text = f"@{self.cfg.bot_names[0]} {msg.text}".strip()
        self.store.add(grp.alias, msg.msg_id, msg.ts, msg.user_id, msg.name, msg.text, msg.reply_to)
        grp.add(msg, called)

    # ---- tools (called by a group's harness through MCP; CALLER says which group) ----
    async def send(self, text: str) -> str:
        grp, text = CALLER.get(), text.strip()
        if grp is None or not grp.in_turn:
            return "现在没有进行中的对话，不能发送。"
        if not text:
            return "内容为空，没有发送。"
        if grp.sends >= self.cfg.max_sends_per_turn:
            return "这一轮已经发够了，没有发送。结束这一轮。"
        if self.conn is None:
            return "QQ 没连上，没有发送。不要重试。"
        text = text[: self.cfg.max_message_chars]
        name = self.cfg.bot_names[0]
        grp.sends += 1
        try:
            data = await self.conn.call("send_group_msg", {"group_id": int(grp.group_id), "message": [{"type": "text", "data": {"text": text}}]},
                                        self.cfg.send_timeout_s)
        except SendUnknown:
            self.store.add(grp.alias, "", time.time(), self.self_id or "self", name, text)
            return "发送状态不明（可能已经发出）。不要重发，结束这一轮。"
        except RuntimeError as e:
            grp.sends -= 1
            return f"发送失败：{e}"
        self.store.add(grp.alias, str(data.get("message_id", "")), time.time(), self.self_id or "self", name, text)
        return "已发送。"

    async def look_up(self, question: str) -> str:
        """Web search and page reading in a conversation of their own; the group's session gets the conclusion only."""
        cfg, grp = self.cfg, CALLER.get()
        answer, used = await lookup.run(question, model=cfg.model, base_url=cfg.llm_base_url, llm_key=cfg.llm_api_key,
                                        web_key=cfg.search_api_key, timeout=cfg.lookup_timeout_s)
        if grp is not None:
            grp.lookups.append(used)
        return answer

    # ---- serving ----
    def asgi(self):
        cfg = self.cfg
        server = tools.build(self.store, self, lambda: g.alias if (g := CALLER.get()) else "", tuple(cfg.history_exclude),
                             lookup=self.look_up if cfg.search_api_key else None)
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
