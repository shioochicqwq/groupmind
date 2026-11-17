"""A bot host with a real harness process and everything else stood in for, for the handoff tests.

The model is a scripted OpenAI-compatible endpoint: a group line carrying `[[call TOOL {json}]]` makes it call
that tool, one marker per step; a tool result that asks for a wrap-up gets the 【回复】/【摘要】 answer. Every
request it gets is kept, so a test can look at exactly what each session was shown. The QQ side is a fake
connection that keeps what was sent. The video watcher waits until the test lets a video finish.
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import socket
import time
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from bothost.app import Host
from bothost.config import Config

GROUP, SELF = "100001", "20000"
HAVE_DSH = shutil.which("dsh") is not None
CALL = re.compile(r"\[\[call (\S+) (\{.*?\})\]\]")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def text_of(m: dict) -> str:
    c = m.get("content")
    return c if isinstance(c, str) else "".join(p.get("text", "") for p in c or [] if isinstance(p, dict))


def newest(messages: list[dict]) -> int:
    return max(i for i, m in enumerate(messages) if m["role"] == "user" and not text_of(m).startswith("Current runtime context"))


def tiny_png() -> bytes:
    import struct
    import zlib

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + \
        chunk(b"IDAT", zlib.compress(b"\x00\xff\x80\x00")) + chunk(b"IEND", b"")


def has_image(message: dict) -> bool:
    c = message.get("content")
    return isinstance(c, list) and any(isinstance(p, dict) and p.get("type") in ("image_url", "image") for p in c)


def script(messages: list[dict]) -> dict:
    """What the scripted model says next: {"text": ...} or {"call": (name, args)}."""
    # the harness adds its own "Current runtime context" line after a prompt; the group's lines are the user message before it
    last_user = newest(messages)
    if any(has_image(m) for m in messages[last_user:]) and not any(m["role"] == "assistant" for m in messages[last_user:]):
        return {"text": "（不接话）\n【图片1】一只橘猫在键盘上睡觉"}
    since = messages[last_user + 1:]
    results = [text_of(m) for m in since if m["role"] == "tool"]
    made = [c for m in since if m["role"] == "assistant" for c in m.get("tool_calls") or []]
    if any("【回复】给" in r for r in results):   # a background session wrapping up
        if any("TRY-SEND" in r for r in results) and not any(c["function"]["name"].endswith("send_group_message") for c in made):
            return {"call": ("mcp__qq__send_group_message", {"text": "偷偷说一句"})}
        got = next(r for r in results if "【回复】给" in r)
        summary = {"task": "看了", "observed": [got[:20]], "inferred": [], "conclusion": "看完了", "memory_candidates": ["候选事实"],
                   "people": [{"name": "阿橘", "impression": "爱发视频"}]}
        return {"text": f"【回复】结果是：{got[:12]}\n【摘要】{json.dumps(summary, ensure_ascii=False)}"}
    markers = CALL.findall(text_of(messages[last_user]))
    if len(made) < len(markers):
        name, args = markers[len(made)]
        return {"call": (name, json.loads(args))}
    return {"text": "（完）"}


class FakeModel:
    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.n = 0
        self.sticker_calls = 0

    def asked(self, words: str) -> list[dict]:
        """The requests whose newest group lines contain `words`."""
        return [q for q in self.requests if words in text_of(q["messages"][newest(q["messages"])])]

    async def chat(self, request: Request):
        body = await request.json()
        self.n += 1
        n = self.n
        self.requests.append(body)
        ms = body["messages"]
        if not body.get("tools") and "表情包" in text_of(ms[0]):   # the sticker call of its own: slow on purpose
            self.sticker_calls += 1
            await asyncio.sleep(2)
            return JSONResponse({"id": "s", "object": "chat.completion", "model": body["model"], "usage": {"prompt_tokens": 50, "completion_tokens": 9},
                                 "choices": [{"index": 0, "message": {"role": "assistant", "content": "翻白眼，表示无语"}, "finish_reason": "stop"}]})
        if "[[hang]]" in text_of(ms[newest(ms)]) and ms[-1]["role"] != "tool":   # a model stream that never comes back
            await asyncio.sleep(3600)
        say = script(body["messages"])
        if "call" in say:
            delta = {"role": "assistant", "content": None, "tool_calls": [{"index": 0, "id": f"call_{n}", "type": "function",
                     "function": {"name": say["call"][0], "arguments": json.dumps(say["call"][1], ensure_ascii=False)}}]}
            finish = "tool_calls"
        else:
            delta, finish = {"role": "assistant", "content": say["text"]}, "stop"
        usage = {"prompt_tokens": 100, "completion_tokens": 5, "total_tokens": 105}

        def chunk(d, fin=None, u=None):
            return "data: " + json.dumps({"id": f"c{n}", "object": "chat.completion.chunk", "created": int(time.time()), "model": body["model"],
                                          "choices": [{"index": 0, "delta": d, "finish_reason": fin}], **({"usage": u} if u else {})}) + "\n\n"

        async def stream():
            yield chunk(delta)
            yield chunk({}, finish, usage)
            yield "data: [DONE]\n\n"
        if body.get("stream"):
            return StreamingResponse(stream(), media_type="text/event-stream")
        return JSONResponse({"id": f"c{n}", "object": "chat.completion", "model": body["model"], "usage": usage,
                             "choices": [{"index": 0, "message": delta, "finish_reason": finish}]})


class FakeConn:
    def __init__(self) -> None:
        self.sent: list[dict] = []           # group messages
        self.other: list[tuple[str, dict]] = []   # any other action, e.g. a private message

    async def call(self, action: str, params: dict, timeout: float) -> dict:
        if action != "send_group_msg":
            self.other.append((action, params))
            return {"message_id": 800 + len(self.other)}
        self.sent.append(params)
        return {"message_id": 900 + len(self.sent)}

    def close(self) -> None:
        pass

    def texts(self) -> list[str]:
        return [s["data"]["text"] for p in self.sent for s in p["message"] if s["type"] == "text"]

    def quoted(self) -> list[tuple[str, str]]:
        """(quoted message id, text) of the messages sent as replies."""
        out = []
        for p in self.sent:
            ids = [s["data"]["id"] for s in p["message"] if s["type"] == "reply"]
            if ids:
                out.append((ids[0], "".join(s["data"]["text"] for s in p["message"] if s["type"] == "text")))
        return out


class FakeWatcher:
    """A video finishes when the test says so; its result is long, so a leak into another session shows."""

    def __init__(self, rig: "Rig") -> None:
        self.rig, self.done, self.started = rig, {}, []

    async def ask(self, url, question, start=-1, end=-1):
        self.started.append((url, time.monotonic(), self.rig.tasks()))
        await self.done.setdefault(url, asyncio.Event()).wait()
        return f"视频里 PAYLOAD-{url} " + "很长的画面描述" * 400, {"calls": 1, "prompt": 10, "completion": 5, "seconds": 0.1}


class Rig:
    def __init__(self, tmp: Path, handoff: bool = True, **cfg) -> None:
        self.tmp, self.model, self.conn = tmp, FakeModel(), FakeConn()
        self.llm_port, self.port = free_port(), free_port()
        self.cfg = Config(data_dir=tmp / "data", bot_names=["小机"], groups={GROUP: "g1"}, model="fake",
                          llm_base_url=f"http://127.0.0.1:{self.llm_port}/v1", listen_port=self.port, debounce_s=0.05,
                          handoff=handoff, video_model="fake-video", llm_api_key="x", **cfg)
        self.msg_id = 100

    async def __aenter__(self) -> "Rig":
        app = Starlette(routes=[Route("/v1/chat/completions", self.model.chat, methods=["POST"]),
                                Route("/img.png", lambda request: Response(tiny_png(), media_type="image/png"))])
        self.llm = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=self.llm_port, log_level="warning",
                                                  timeout_graceful_shutdown=1))
        self.llm_task = asyncio.create_task(self.llm.serve())
        self.host = Host(self.cfg)
        self.host.watcher = FakeWatcher(self)
        self.host.conn, self.host.self_id = self.conn, SELF
        self.serving = asyncio.create_task(self.host.serve())
        await self.until(lambda: self.llm.started and self.serving and not self.serving.done(), 10)
        await asyncio.sleep(0.5)
        return self

    async def __aexit__(self, *exc) -> None:
        for g in self.host.groups.values():
            await g.dsh.kill()
        self.serving.cancel()
        self.llm.should_exit = True
        await asyncio.gather(self.serving, self.llm_task, return_exceptions=True)

    @property
    def group(self):
        return self.host.groups[GROUP]

    def say(self, name: str, text: str, at: bool = True) -> str:
        self.msg_id += 1
        segs = ([{"type": "at", "data": {"qq": SELF}}] if at else []) + [{"type": "text", "data": {"text": text}}]
        self.host.on_event({"post_type": "message", "message_type": "group", "self_id": int(SELF), "group_id": int(GROUP),
                            "message_id": self.msg_id, "time": int(time.time()), "user_id": 1000 + sum(map(ord, name)) % 9000,
                            "sender": {"card": name, "nickname": name}, "message": segs})
        return str(self.msg_id)

    def tasks(self) -> list[dict]:
        if self.host.handoff is None:
            return []
        return [dict(r) for r in self.host.handoff.db.execute("SELECT * FROM task ORDER BY started")]

    def active(self) -> str:
        r = self.host.handoff.db.execute("SELECT session FROM active WHERE grp = 'g1'").fetchone()
        return r[0] if r else ""

    def events(self, *types: str) -> list[dict]:
        rows = self.host.handoff.db.execute("SELECT * FROM event ORDER BY seq").fetchall()
        return [dict(r) for r in rows if not types or r["type"] in types]

    def finish_video(self, url: str) -> None:
        self.host.watcher.done.setdefault(url, asyncio.Event()).set()

    def idle(self) -> bool:
        g = self.group
        return g.current is None and g.due is None and not g.pending

    async def until(self, cond, timeout: float = 30.0) -> None:
        end = time.monotonic() + timeout
        while not cond():
            if time.monotonic() > end:
                raise AssertionError("condition not reached in time")
            await asyncio.sleep(0.05)


def call(tool: str, **args) -> str:
    return f"[[call mcp__qq__{tool} {json.dumps(args, ensure_ascii=False)}]]"


def dangling(messages: list[dict]) -> set[str]:
    """Tool calls in a model request without a matching result."""
    asked = {c["id"] for m in messages if m["role"] == "assistant" for c in m.get("tool_calls") or []}
    return asked - {m.get("tool_call_id") for m in messages if m["role"] == "tool"}
