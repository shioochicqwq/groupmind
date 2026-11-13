"""OneBot v11: turn group-message events into plain lines, and call actions over the same socket."""
from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from typing import Any

PLACEHOLDER = {"image": "[图片]", "face": "[表情]", "mface": "[表情]", "record": "[语音]", "video": "[视频]",
               "file": "[文件]", "forward": "[转发消息]", "json": "[卡片]"}


@dataclass
class Msg:
    group_id: str
    msg_id: str
    ts: int
    user_id: str
    name: str
    text: str
    at_me: bool = False
    reply_to: str = ""


def parse_group_message(ev: dict[str, Any]) -> Msg | None:
    """None for anything that is not a group message."""
    if ev.get("post_type") != "message" or ev.get("message_type") != "group":
        return None
    self_id = str(ev.get("self_id", ""))
    sender = ev.get("sender") or {}
    segments = ev.get("message")
    parts: list[str] = []
    at_me, reply_to = False, ""
    if isinstance(segments, list):
        for seg in segments:
            kind, data = seg.get("type"), seg.get("data") or {}
            if kind == "text":
                parts.append(str(data.get("text", "")))
            elif kind == "at":
                target = str(data.get("qq", ""))
                if target == self_id:
                    at_me = True
                else:
                    parts.append("@全体成员 " if target == "all" else f"@{data.get('name') or '某人'} ")
            elif kind == "reply":
                reply_to = str(data.get("id", ""))
            else:
                parts.append(PLACEHOLDER.get(kind, f"[{kind}]"))
    else:  # string format: keep as is, the deployment should use the array format
        parts.append(str(ev.get("raw_message") or segments or ""))
    return Msg(group_id=str(ev.get("group_id", "")), msg_id=str(ev.get("message_id", "")), ts=int(ev.get("time") or 0),
               user_id=str(ev.get("user_id", "")), name=str(sender.get("card") or sender.get("nickname") or "群友"),
               text="".join(parts).strip(), at_me=at_me, reply_to=reply_to)


class SendUnknown(Exception):
    """The action was written to the socket but no answer came back: it may or may not have happened."""


class Connection:
    """One live socket from the protocol side. `send_json` is whatever writes a JSON frame."""

    def __init__(self, send_json) -> None:
        self._send = send_json
        self._waiting: dict[str, asyncio.Future] = {}

    def feed(self, frame: dict[str, Any]) -> bool:
        """True if the frame was an action response."""
        fut = self._waiting.pop(str(frame.get("echo", "")), None) if "post_type" not in frame else None
        if fut is None:
            return False
        if not fut.done():
            fut.set_result(frame)
        return True

    async def call(self, action: str, params: dict[str, Any], timeout: float) -> dict[str, Any]:
        echo = uuid.uuid4().hex
        fut = asyncio.get_running_loop().create_future()
        self._waiting[echo] = fut
        await self._send(json.dumps({"action": action, "params": params, "echo": echo}, ensure_ascii=False))
        try:
            frame = await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError as e:
            self._waiting.pop(echo, None)
            raise SendUnknown(action) from e
        if frame.get("status") != "ok":
            raise RuntimeError(f"{action} failed: retcode {frame.get('retcode')}")
        return frame.get("data") or {}

    def close(self) -> None:
        for fut in self._waiting.values():
            if not fut.done():
                fut.set_exception(SendUnknown("connection closed"))
        self._waiting.clear()
