"""Client for `dsh --profile sdk-minimal`: JSON-RPC 2.0 over stdio, one JSON object per line."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

log = logging.getLogger("bothost.harness")
USAGE = re.compile(r'"usage":\s*(\{[^{}]*\})')


class HarnessError(Exception):
    pass


class TurnTimeout(HarnessError):
    """The turn did not finish in time, or (with a stall limit) stopped moving and did not end when cancelled.
    `usage` is what the model calls had cost up to then."""

    def __init__(self, usage: dict[str, int]) -> None:
        super().__init__("timeout")
        self.usage = usage


class Dsh:
    def __init__(self, cmd: list[str], patches: list[str], home: Path, workspace: Path, env: dict[str, str],
                 provider: str, model: str) -> None:
        self.cmd, self.patches, self.home, self.workspace = cmd, patches, home, workspace
        self.env, self.provider, self.model = env, provider, model
        self.proc: asyncio.subprocess.Process | None = None
        self._id = 0
        self._waiting: dict[int, asyncio.Future] = {}
        self._status: dict[str, asyncio.Queue] = {}
        self._usage: dict[str, dict[str, int]] = {}
        self._failed: dict[str, str] = {}   # session -> short error code of its last turn
        self._opened: set[str] = set()
        # For session handoff: tool calls started and not answered yet, and what the model last wrote, per session.
        self.open_calls: dict[str, dict[str, tuple[str, dict]]] = {}   # session -> call id -> (tool name, arguments)
        self.last_text: dict[str, str] = {}
        self.notes_written: dict[str, list[str]] = {}   # session -> compaction notes the model wrote, not yet read by the host
        self._call_seen = asyncio.Event()
        self.last_event: dict[str, float] = {}   # session -> when it last did anything (monotonic)
        # With handoff the plugin (deploy/dsh/handoff.mjs) opens, prompts and closes sessions; the SDK is left with
        # initialize and the notifications. Without it, sessions are the SDK's, as before.
        self.handoff_port = int(env.get("QQBOT_HANDOFF_PORT") or 0)
        self.handoff_token = env.get("QQBOT_HANDOFF_TOKEN", "")
        self.handoff_sock = bool(self.handoff_port) and env.get("QQBOT_PLUGIN_SESSIONS") == "1"   # the plugin owns the sessions
        self.starts = 0   # how many times the process was started; a new process needs its people table set again

    async def _ensure_started(self) -> None:
        if self.proc is not None and self.proc.returncode is None:
            return
        self.home.mkdir(parents=True, exist_ok=True)
        self.workspace.mkdir(parents=True, exist_ok=True)
        args = [*self.cmd, "--profile", "sdk-minimal"]
        for p in self.patches:
            args += ["--patch", p]
        stderr = open(self.home / "dsh.stderr.log", "ab")
        self.proc = await asyncio.create_subprocess_exec(
            *args, cwd=self.workspace, env={**os.environ, **self.env, "DSH_HOME": str(self.home)},
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=stderr, limit=64 * 1024 * 1024)
        self._opened.clear()
        self.open_calls.clear()
        self.starts += 1
        asyncio.create_task(self._read(self.proc))
        await self.call("initialize", {"cwd": str(self.workspace), "provider": self.provider, "model": self.model}, 120)
        log.info("harness ready")

    async def _read(self, proc: asyncio.subprocess.Process) -> None:
        assert proc.stdout is not None
        while line := await proc.stdout.readline():
            try:
                m = json.loads(line)
            except ValueError:
                continue
            if "id" in m and "method" not in m:
                fut = self._waiting.pop(m["id"], None)
                if fut and not fut.done():
                    fut.set_exception(HarnessError(str(m["error"].get("message")))) if "error" in m else fut.set_result(m.get("result"))
                continue
            p = m.get("params") or {}
            sid = p.get("sessionId", "")
            if sid:
                self.last_event[sid] = asyncio.get_running_loop().time()
            if m.get("method") == "session.status":
                self._status.setdefault(sid, asyncio.Queue()).put_nowait(p.get("status"))
            elif m.get("method") == "session.event" and (p.get("event") or {}).get("type") == "turn/end":
                reason = (p["event"].get("data") or {}).get("reason") or {}
                if reason.get("kind") == "error":
                    err = reason.get("error") or {}
                    self._failed[sid] = str(err.get("code") or str(err.get("message", ""))[:3] or "error")
            elif m.get("method") == "session.event" and (p.get("event") or {}).get("type") == "tool/call":
                d = p["event"].get("data") or {}
                try:
                    args = d.get("arguments")
                    args = json.loads(args) if isinstance(args, str) else dict(args or {})
                except (ValueError, TypeError):
                    args = {}
                self.open_calls.setdefault(sid, {})[str(d.get("callId", ""))] = (str(d.get("name", "")), args)
                self._call_seen.set()
            elif m.get("method") == "session.event" and (p.get("event") or {}).get("type") == "tool/result":
                d = p["event"].get("data") or {}
                cid = d.get("callId") or (d.get("message") or {}).get("toolCallId")
                self.open_calls.get(sid, {}).pop(str(cid), None)
            elif m.get("method") == "session.event" and (p.get("event") or {}).get("type") == "assistant/message":
                parts = ((p["event"].get("data") or {}).get("message") or {}).get("content") or []
                said = "".join(x.get("text", "") for x in parts if isinstance(x, dict) and x.get("type") == "text").strip()
                if said:
                    self.last_text[sid] = said
                u = USAGE.search(json.dumps(p["event"]))
                if u:
                    d = json.loads(u.group(1))
                    acc = self._usage.setdefault(sid, {"calls": 0, "prompt": 0, "completion": 0})
                    acc["calls"] += 1
                    acc["prompt"] += int(d.get("inputTokens") or 0)   # input not served from the provider's cache
                    if d.get("cacheReadTokens"):
                        acc["cached"] = acc.get("cached", 0) + int(d["cacheReadTokens"])
                    acc["completion"] += int(d.get("outputTokens") or 0)
            elif m.get("method") == "session.event" and (p.get("event") or {}).get("type") == "compaction/summary":
                # The harness replaced the oldest part of the session with a summary. Its model call is counted apart.
                d = p["event"].get("data") or {}
                note = "".join(b.get("text", "") for b in d.get("summary") or [] if isinstance(b, dict))
                if note:
                    self.notes_written.setdefault(sid, []).append(note)
                u = d.get("usage") or {}
                acc = self._usage.setdefault(sid, {"calls": 0, "prompt": 0, "completion": 0})
                acc["compactions"] = acc.get("compactions", 0) + 1
                acc["compact_prompt"] = acc.get("compact_prompt", 0) + int(u.get("inputTokens") or 0)
                acc["compact_completion"] = acc.get("compact_completion", 0) + int(u.get("outputTokens") or 0)
                if u.get("cacheReadTokens"):
                    acc["compact_cached"] = acc.get("compact_cached", 0) + int(u["cacheReadTokens"])
        for fut in self._waiting.values():
            if not fut.done():
                fut.set_exception(HarnessError("harness exited"))
        self._waiting.clear()
        for q in self._status.values():
            q.put_nowait("exited")

    async def call(self, method: str, params: dict[str, Any] | None, timeout: float) -> Any:
        assert self.proc is not None and self.proc.stdin is not None
        self._id += 1
        msg: dict[str, Any] = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            msg["params"] = params
        fut = asyncio.get_running_loop().create_future()
        self._waiting[self._id] = fut
        self.proc.stdin.write((json.dumps(msg, ensure_ascii=False) + "\n").encode())
        await self.proc.stdin.drain()
        return await asyncio.wait_for(fut, timeout)

    async def open(self, session: str) -> bool:
        """Make the session usable in this process. True if it is new, False if history was restored."""
        await self._ensure_started()
        if session in self._opened:
            return False
        if self.handoff_sock:
            new = (await self.plugin("open", session=session))["new"]
            self._opened.add(session)
            return new
        try:
            await self.call("session/resume", {"sessionId": session}, 120)
            new = False
        except HarnessError:
            new = True  # nothing stored under this id; a real conflict surfaces on the first prompt
        self._opened.add(session)
        return new

    async def turn(self, session: str, text: str, timeout: float = 0.0, stall: float | None = None,
                   images: list[tuple[str, str, str]] = ()) -> dict[str, int]:
        """Queue one user message and wait until the agent is idle again. Returns token usage for the turn,
        plus "error" (a short code) when the harness ended the turn on a failure, e.g. the model route was down.

        timeout: a limit on the whole turn. stall: instead, no limit on the whole turn, only on standing still (see _watch).
        images: (label, base64 data, media type) each, sent after the text, every one after its label."""
        await self._ensure_started()
        q = self._status[session] = asyncio.Queue()
        self._usage.pop(session, None)
        self._failed.pop(session, None)
        blocks: list[dict] = [{"type": "text", "text": text}]
        for label, data, mime in images:
            blocks += [{"type": "text", "text": label}, {"type": "image", "data": data, "mimeType": mime}]
        if self.handoff_sock:
            await self.plugin("prompt", session=session, text=text, blocks=blocks)
        else:
            await self.call("session/prompt", {"sessionId": session, "contentBlocks": blocks}, 60)

        async def until_idle() -> None:
            ran = False
            while True:
                s = await q.get()
                if s == "exited":
                    raise HarnessError("harness exited during the turn")
                ran = ran or s == "running"
                if s == "idle" and ran:
                    return
        try:
            if stall is None:
                await asyncio.wait_for(until_idle(), timeout)
            else:
                await self._watch(session, asyncio.ensure_future(until_idle()), stall)
        except asyncio.TimeoutError:
            raise TurnTimeout(self._usage.pop(session, {"calls": 0, "prompt": 0, "completion": 0})) from None
        usage = self._usage.pop(session, {"calls": 0, "prompt": 0, "completion": 0})
        if session in self._failed:
            usage["error"] = self._failed.pop(session)
        return usage

    async def find_call(self, name: str, given: dict[str, Any], wait: float = 3.0) -> tuple[str, str] | None:
        """(session, call id) of the open call of tool `name` whose arguments match what the tool was given.
        The tool's HTTP request and the harness's note of the call travel apart, so the note may come a moment later."""
        loop = asyncio.get_running_loop()
        until = loop.time() + wait
        while True:
            for sid, calls in self.open_calls.items():
                for cid, (tool, args) in calls.items():
                    if tool == name and all(str(args.get(k, "")).strip() == str(v).strip() for k, v in given.items()):
                        return sid, cid
            left = until - loop.time()
            if left <= 0:
                return None
            self._call_seen.clear()
            try:
                await asyncio.wait_for(self._call_seen.wait(), left)
            except asyncio.TimeoutError:
                return None

    async def plugin(self, op: str, **args: Any) -> dict:
        """One request to the handoff plugin (deploy/dsh/handoff.mjs)."""
        if not self.handoff_port:
            raise HarnessError("host plugin not configured")
        await self._ensure_started()
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", self.handoff_port), 10)
        except (OSError, asyncio.TimeoutError) as e:
            raise HarnessError(f"handoff plugin unreachable: {type(e).__name__}") from None
        try:
            writer.write((json.dumps({"op": op, "token": self.handoff_token, **args}, ensure_ascii=False) + "\n").encode())
            await writer.drain()
            out = json.loads(await asyncio.wait_for(reader.readline(), 120))
        finally:
            writer.close()
        if "error" in out:
            raise HarnessError(f"{op} failed: {out['error']}")
        return out["ok"]

    async def fork(self, source: str, child: str, call_id: str) -> dict:
        """A new session `child` with `source`'s history up to before the model message that made `call_id`.
        `source` keeps running; its call still returns to it."""
        out = await self.plugin("fork", source=source, child=child, callId=call_id)
        self._opened.add(child)
        return out

    async def close(self, session: str) -> None:
        """Take a session out of memory (its log stays on disk). Only sessions the plugin opened."""
        if not self.handoff_sock or session not in self._opened or self.proc is None or self.proc.returncode is not None:
            return
        self._opened.discard(session)
        for d in (self.open_calls, self.last_text, self.last_event, self._status):
            d.pop(session, None)
        await self.plugin("close", session=session)

    async def _watch(self, session: str, idle: asyncio.Future, stall: float) -> None:
        """Wait for the turn however long it takes. Only standing still counts: no event from the session for `stall`
        seconds while none of its tool calls is out (a tool call is the host's own work and ends on its own).
        Then that one session is cancelled; the process and the other sessions go on."""
        loop = asyncio.get_running_loop()
        self.last_event[session] = loop.time()
        while True:
            quiet = loop.time() - self.last_event.get(session, loop.time())
            try:
                await asyncio.wait_for(asyncio.shield(idle), max(1.0, stall - quiet))
                return
            except asyncio.TimeoutError:
                pass
            if self.open_calls.get(session):   # a tool is running: that is work, not standing still
                self.last_event[session] = loop.time()
                continue
            if loop.time() - self.last_event.get(session, 0) < stall:
                continue
            log.warning("session %s has not moved for %.0fs; cancelling it", session, stall)
            try:
                await self.plugin("cancel", session=session)
                await asyncio.wait_for(asyncio.shield(idle), 60)
                self._failed[session] = "stalled"
                return
            except (HarnessError, asyncio.TimeoutError):
                idle.cancel()
                raise asyncio.TimeoutError from None

    async def kill(self) -> None:
        """Drop the process without waiting, e.g. after a turn that never came back. The next call starts a new one;
        sessions are on disk and get resumed."""
        if self.proc is not None and self.proc.returncode is None:
            self.proc.kill()
            await self.proc.wait()

    async def stop(self) -> None:
        if self.proc is None or self.proc.returncode is not None:
            return
        try:
            await self.call("shutdown", None, 20)
            await asyncio.wait_for(self.proc.wait(), 20)
        except (HarnessError, asyncio.TimeoutError, ConnectionError):
            self.proc.terminate()
