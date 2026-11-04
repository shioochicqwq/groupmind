"""Load a ChatLab JSONL group export. Real data stays outside the repository."""
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from bench.schema import Message

TEXT_TYPE = 0


def iter_records(path: Path) -> Iterator[dict]:
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def load(path: Path, channel: str) -> list[Message]:
    """channel is a pseudonym chosen by the caller, never the real group id."""
    out = []
    for r in iter_records(path):
        if r.get("_type") != "message":
            continue
        kind = r.get("type", TEXT_TYPE)
        media = () if kind == TEXT_TYPE else (str(kind),)
        out.append(
            Message(
                msg_id=str(r["platformMessageId"]),
                channel=channel,
                author=str(r["sender"]),
                timestamp=float(r["timestamp"]),
                content=(r.get("content") or "").strip(),
                reply_to=str(r["replyToMessageId"]) if r.get("replyToMessageId") else None,
                media=media,
                nickname_at_time=r.get("groupNickname") or r.get("accountName") or "",
            )
        )
    out.sort(key=lambda m: (m.timestamp, m.msg_id))
    return out
