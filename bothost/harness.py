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
    """The turn did not finish in time. `usage` is what the model calls had cost up to then."""

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
            if m.get("method") == "session.status":
                self._status.setdefault(sid, asyncio.Queue()).put_nowait(p.get("status"))
            elif m.get("method") == "session.event" and (p.get("event") or {}).get("type") == "turn/end":
                reason = (p["event"].get("data") or {}).get("reason") or {}
                if reason.get("kind") == "error":
                    err = reason.get("error") or {}
                    self._failed[sid] = str(err.get("code") or str(err.get("message", ""))[:3] or "error")
            elif m.get("method") == "session.event" and (p.get("event") or {}).get("type") == "assistant/message":
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
        try:
            await self.call("session/resume", {"sessionId": session}, 120)
            new = False
        except HarnessError:
            new = True  # nothing stored under this id; a real conflict surfaces on the first prompt
        self._opened.add(session)
        return new

    async def turn(self, session: str, text: str, timeout: float) -> dict[str, int]:
        """Queue one user message and wait until the agent is idle again. Returns token usage for the turn,
        plus "error" (a short code) when the harness ended the turn on a failure, e.g. the model route was down."""
        await self._ensure_started()
        q = self._status[session] = asyncio.Queue()
        self._usage.pop(session, None)
        self._failed.pop(session, None)
        await self.call("session/prompt", {"sessionId": session, "contentBlocks": [{"type": "text", "text": text}]}, 60)

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
            await asyncio.wait_for(until_idle(), timeout)
        except asyncio.TimeoutError:
            raise TurnTimeout(self._usage.pop(session, {"calls": 0, "prompt": 0, "completion": 0})) from None
        usage = self._usage.pop(session, {"calls": 0, "prompt": 0, "completion": 0})
        if session in self._failed:
            usage["error"] = self._failed.pop(session)
        return usage

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
