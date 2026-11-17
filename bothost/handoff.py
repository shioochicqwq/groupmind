"""Session handoff: when the group's session starts something slow, a copy of it takes over the group.

The session that started the slow work (A) keeps running in the background with its own tool call; a new
session (B), copied from A up to before the model message that made the call (deploy/dsh/handoff.mjs), becomes
the one that talks in the group. When A is done it gives one reply, quoting the message that asked for the work,
and a short account of what it did; both reach whichever session is active then, at the start of its next turn.

Only the host decides when (bothost/app.py: a video, or page reading about to start a browser); no timer and no
extra model call. Per group there is one active session; tasks may be several. Everything is kept in one SQLite
file, so a restart knows which session is active and which tasks were cut off.

Session states: ACTIVE -> DETACHED -> COMPLETED | FAILED -> RETIRED. Task states: running -> completed | failed.
"""
from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from .store import stamp

SCHEMA = """
CREATE TABLE IF NOT EXISTS event(seq INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, grp TEXT NOT NULL, session TEXT,
    task TEXT, type TEXT NOT NULL, source_msg TEXT, payload TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS task(id TEXT PRIMARY KEY, grp TEXT NOT NULL, session TEXT NOT NULL, successor TEXT NOT NULL,
    call_id TEXT NOT NULL, kind TEXT NOT NULL, detail TEXT, source_msg TEXT, source TEXT, status TEXT NOT NULL,
    started REAL NOT NULL, finished REAL, reply TEXT, summary TEXT, UNIQUE(session, call_id));
CREATE TABLE IF NOT EXISTS session(id TEXT PRIMARY KEY, grp TEXT NOT NULL, state TEXT NOT NULL, generation INTEGER NOT NULL,
    parent TEXT, changed REAL NOT NULL);
CREATE TABLE IF NOT EXISTS active(grp TEXT PRIMARY KEY, session TEXT NOT NULL, base TEXT NOT NULL, generation INTEGER NOT NULL,
    delivered INTEGER NOT NULL DEFAULT 0);
"""
KINDS = {"video": "看视频", "l3": "用浏览器读网页", "known_l3": "用浏览器读网页"}
NOTE_TYPES = ("handoff", "task_completed", "task_failed")

# Added to the slow tool's result when it comes back to a session that no longer has the group.
WRAP_UP = """

（系统：群聊已经由你的另一个会话接着聊了，你这边只负责把这件事收尾。不要再调用 send_group_message。需要的话可以再查，查完直接在正文按下面的格式写完就结束：
【回复】给{who}的回复，会引用对方那条消息发到群里。一两句，像平时说话；结果不好或没看成也照实说。实在不用回复就写「无」。
【摘要】一个 JSON：{{"task": "做了什么", "link": "链接", "observed": ["真的看到、读到的"], "inferred": ["推断出来的"], "conclusion": "结论", "sources": ["来源或视频时间点"], "failures": "没做成或不确定的", "memory_candidates": ["以后值得记住的事实"], "people": [{{"name": "群消息前显示的名字", "alias": "外号", "impression": "一句印象", "attitude": "你对 ta 的态度"}}]}}
people 只写这件事里新认识的人、或者对谁的看法变了；没有就写空列表。
只写真的看到的，没看到的不要编。）"""


@dataclass
class Origin:
    """The group message the slow work answers."""
    msg_id: str
    ts: float
    name: str
    text: str

    def show(self) -> str:
        return f"{self.name} 在 {stamp(self.ts, '%m-%d %H:%M')} 的消息「{self.text[:60]}」"


def wrap_up(origin: Origin | None) -> str:
    return WRAP_UP.format(who=origin.name if origin else "问的人")


def parse_wrap_up(text: str) -> tuple[str, dict]:
    """(reply, summary) from the detached session's last words. The reply is empty when there is none to send."""
    reply, summary = "", {}
    m = re.search(r"【回复】(.*?)(?:【摘要】|$)", text, re.S)
    if m:
        reply = m.group(1).strip()
        if reply in ("无", "无。", "（无）"):
            reply = ""
    s = re.search(r"【摘要】(.*)", text, re.S)
    raw = s.group(1).strip() if s else ("" if m else text.strip())
    j = re.search(r"\{.*\}", raw, re.S)
    if j:
        try:
            summary = json.loads(j.group(0))
        except ValueError:
            summary = {}
    if not summary and raw:
        summary = {"unstructured": raw[:1500]}
    return reply, summary


class Handoff:
    def __init__(self, path: str | Path, max_tasks: int = 2, max_total: int = 4) -> None:
        self.db = sqlite3.connect(path, timeout=30, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        self.max_tasks, self.max_total = max_tasks, max_total
        self.locks: dict[str, asyncio.Lock] = {}

    # ---- the active pointer ----
    def active(self, grp: str, base: str) -> str:
        """The session that talks in the group. `base` is the session name without handoff (the alias, or alias and
        date); a new base (a new day) starts from itself, so a pointer left from before does not carry over."""
        r = self.db.execute("SELECT session, base, generation FROM active WHERE grp = ?", (grp,)).fetchone()
        if r and r["base"] == base:
            return r["session"]
        gen = r["generation"] + 1 if r else 0
        with self._tx():
            self.db.execute("INSERT INTO active(grp, session, base, generation) VALUES (?, ?, ?, ?) ON CONFLICT(grp) DO UPDATE SET "
                            "session = excluded.session, base = excluded.base, generation = excluded.generation", (grp, base, base, gen))
            self._state(base, grp, "ACTIVE", gen, None)
            if r:
                self._state(r["session"], grp, "RETIRED", r["generation"], None, only_if="ACTIVE")
        return base

    def is_active(self, grp: str, session: str) -> bool:
        r = self.db.execute("SELECT session FROM active WHERE grp = ?", (grp,)).fetchone()
        return bool(r) and r["session"] == session

    def state(self, session: str) -> str:
        r = self.db.execute("SELECT state FROM session WHERE id = ?", (session,)).fetchone()
        return r["state"] if r else ""

    # ---- handing over ----
    async def hand_over(self, grp: str, session: str, call_id: str, kind: str, detail: str, origin: Origin | None,
                        fork: Callable[[str], Awaitable[object]]) -> tuple[str, str] | None:
        """(task id, new session) when `session` handed the group over for this call; None when it does not
        (not the active session, too many tasks running, or the copy failed: the call then runs as before)."""
        async with self.locks.setdefault(grp, asyncio.Lock()):
            done = self.db.execute("SELECT id, successor FROM task WHERE session = ? AND call_id = ?", (session, call_id)).fetchone()
            if done:   # the same call asking again
                return done["id"], done["successor"]
            r = self.db.execute("SELECT session, base, generation FROM active WHERE grp = ?", (grp,)).fetchone()
            if not r or r["session"] != session:
                return None
            here = self.db.execute("SELECT count(*) FROM task WHERE grp = ? AND status = 'running'", (grp,)).fetchone()[0]
            total = self.db.execute("SELECT count(*) FROM task WHERE status = 'running'").fetchone()[0]
            if here >= self.max_tasks or total >= self.max_total:
                self.event(grp, session, None, "handoff_refused", origin, {"kind": kind, "why": "too many tasks", "running": here})
                return None
            gen = r["generation"] + 1
            child = f"{r['base']}-h{gen}"
            try:
                await fork(child)
            except Exception as e:   # nothing changed: the call goes on in the session that made it
                self.event(grp, session, None, "handoff_failed", origin, {"kind": kind, "error": str(e)[:200]})
                return None
            task = uuid.uuid4().hex[:12]
            with self._tx():
                moved = self.db.execute("UPDATE active SET session = ?, generation = ? WHERE grp = ? AND generation = ?",
                                        (child, gen, grp, r["generation"])).rowcount
                if not moved:   # cannot happen under the lock; kept as the check the pointer relies on
                    raise RuntimeError("active pointer changed during a handoff")
                self.db.execute("INSERT INTO task(id, grp, session, successor, call_id, kind, detail, source_msg, source, status, started) "
                                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'running', ?)",
                                (task, grp, session, child, call_id, kind, detail, origin.msg_id if origin else "",
                                 json.dumps(origin.__dict__, ensure_ascii=False) if origin else "", time.time()))
                self._state(session, grp, "DETACHED", r["generation"], None)
                self._state(child, grp, "ACTIVE", gen, session)
                self.event(grp, child, task, "handoff", origin, {"kind": kind, "detail": detail, "from": session})
            return task, child

    # ---- finishing ----
    def task(self, task: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM task WHERE id = ?", (task,)).fetchone()

    def running(self, task: str) -> bool:
        r = self.task(task)
        return bool(r) and r["status"] == "running"

    def finish(self, task: str, ok: bool, reply: str = "", summary: dict | None = None, error: str = "", sent: bool = False) -> bool:
        """Close a task once. False when it was already closed (timed out, cut off by a restart): then nothing is recorded."""
        r = self.task(task)
        with self._tx():
            if not r or not self.db.execute("UPDATE task SET status = ?, finished = ?, reply = ?, summary = ? WHERE id = ? AND status = 'running'",
                                            ("completed" if ok else "failed", time.time(), reply if sent else "",
                                             json.dumps(summary or {}, ensure_ascii=False), task)).rowcount:
                return False
            origin = Origin(**json.loads(r["source"])) if r["source"] else None
            self._state(r["session"], r["grp"], "COMPLETED" if ok else "FAILED", -1, None)
            self.event(r["grp"], r["session"], task, "task_completed" if ok else "task_failed", origin,
                       {"kind": r["kind"], "detail": r["detail"], "reply": reply if sent else "", "summary": summary or {},
                        "error": error, "started": r["started"]})
            self._state(r["session"], r["grp"], "RETIRED", -1, None)
        return True

    def recover(self) -> int:
        """At start: tasks still marked running were cut off when the process stopped."""
        rows = self.db.execute("SELECT id FROM task WHERE status = 'running'").fetchall()
        for r in rows:
            self.finish(r["id"], False, error="机器人重启，后台任务中断了")
        return len(rows)

    # ---- what the active session is told ----
    def notes(self, grp: str) -> tuple[list[str], int]:
        """Lines for the active session's next turn, in the order things were recorded, and the last event number they cover."""
        last = self.db.execute("SELECT delivered FROM active WHERE grp = ?", (grp,)).fetchone()
        after = last["delivered"] if last else 0
        rows = self.db.execute(f"SELECT * FROM event WHERE grp = ? AND seq > ? AND type IN ({','.join('?' * len(NOTE_TYPES))}) ORDER BY seq",
                               (grp, after, *NOTE_TYPES)).fetchall()
        return [note(r) for r in rows], max([after, *(r["seq"] for r in rows)])

    def delivered(self, grp: str, seq: int) -> None:
        self.db.execute("UPDATE active SET delivered = max(delivered, ?) WHERE grp = ?", (seq, grp))

    # ---- records ----
    def event(self, grp: str, session: str | None, task: str | None, kind: str, origin: Origin | None, payload: dict) -> int:
        return self.db.execute("INSERT INTO event(ts, grp, session, task, type, source_msg, payload) VALUES (?, ?, ?, ?, ?, ?, ?)",
                               (time.time(), grp, session, task, kind, origin.msg_id if origin else None,
                                json.dumps({**payload, **({"origin": origin.__dict__} if origin else {})}, ensure_ascii=False))).lastrowid

    def _state(self, session: str, grp: str, state: str, gen: int, parent: str | None, only_if: str = "") -> None:
        if only_if:
            self.db.execute("UPDATE session SET state = ?, changed = ? WHERE id = ? AND state = ?", (state, time.time(), session, only_if))
            return
        self.db.execute("INSERT INTO session(id, grp, state, generation, parent, changed) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
                        "state = excluded.state, changed = excluded.changed", (session, grp, state, gen, parent, time.time()))

    def _tx(self):
        db = self.db

        class Tx:
            def __enter__(self):
                db.execute("BEGIN IMMEDIATE")

            def __exit__(self, kind, *_):
                db.execute("ROLLBACK" if kind else "COMMIT")
        return Tx()


def note(r: sqlite3.Row) -> str:
    """One line for the active session about something recorded in the event log."""
    p = json.loads(r["payload"])
    origin = Origin(**p["origin"]) if p.get("origin") else None
    what = f"{KINDS.get(p.get('kind'), '做一件慢的事')}（{p.get('detail', '')}）"
    about = f"，是为了回 {origin.show()}" if origin else ""
    head = f"[{stamp(r['ts'], '%m-%d %H:%M')}] "
    if r["type"] == "handoff":
        return head + f"你开始{what}{about}。这件事交给后台的你继续做，还没有结果；群聊由现在的你接着聊。没看过的内容不要装作看过，有人问就说还在弄。"
    took = f"，用了 {round((r['ts'] - p['started']) / 60, 1)} 分钟" if p.get("started") else ""
    if r["type"] == "task_completed":
        said = f"已经引用对方的原消息在群里回了：「{p['reply']}」" if p.get("reply") else "没有在群里回复"
        summary = json.dumps(p.get("summary") or {}, ensure_ascii=False)
        return head + f"后台{what}做完了{took}{about}。{said}。经过：{summary}"
    return head + f"后台{what}没做成{about}：{p.get('error') or '原因不明'}。群里还没人知道结果，需要的话由你来说。"
