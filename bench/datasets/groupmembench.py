"""GroupMemBench loader. The data has no stated license: keep it out of this repository."""
from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path

from bench.schema import Message

QTYPES = ("multi_hop", "knowledge_update", "temporal", "user_implicit", "term_ambiguity", "abstention")


def load_messages(repo: Path, domain: str) -> list[Message]:
    path = repo / "data" / "final" / domain / f"synthetic_domain_channels_rolevariants_{domain}.json"
    rows = []
    for channel, msgs in json.loads(path.read_text(encoding="utf-8")).items():
        for m in msgs:
            rows.append((channel, m.get("timestamp", ""), m.get("msg_node", ""), m))
    rows.sort(key=lambda r: r[:3])
    return [
        Message(
            msg_id=m["msg_node"],
            channel=channel,
            author=m.get("author") or "?",
            timestamp=datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() if ts else 0.0,
            content=html.unescape(m.get("content") or "").strip(),
            reply_to=m.get("reply_to"),
        )
        for channel, ts, _, m in rows
    ]


def load_questions(repo: Path, domain: str, qtype: str) -> list[dict]:
    path = repo / "questions" / domain / f"{qtype}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def format_passages(repo: Path, domain: str) -> dict[str, str]:
    """Same header as the official baseline's format_retrieved_message, keyed by message id."""
    path = repo / "data" / "final" / domain / f"synthetic_domain_channels_rolevariants_{domain}.json"
    out = {}
    for channel, msgs in json.loads(path.read_text(encoding="utf-8")).items():
        for m in msgs:
            m = {**m, "_channel": channel}
            tags = [f"user={m.get('author') or '?'}"]
            for key, label in (
                ("role", "speaker_role"), ("_channel", "channel"), ("phase_name", "phase_name"), ("topic", "topic"),
                ("timestamp", "timestamp"), ("reply_to", "reply_to"), ("msg_node", "msg_node"),
            ):
                if m.get(key) not in (None, ""):
                    tags.append(f"{label}={m[key]}")
            out[m["msg_node"]] = f"[{' / '.join(tags)}]\n{html.unescape(m.get('content') or '').strip()}"
    return out
