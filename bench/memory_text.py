"""Render retrieved blocks for a model, showing each raw message once."""
from __future__ import annotations

from collections.abc import Sequence

from bench.sanitize import is_sensitive
from bench.schema import Block, Message


def raw_blocks(blocks: Sequence[Block], by_id: dict[str, Message], limit: int = 1500) -> list[str]:
    """One text per block; messages already shown by an earlier block are dropped."""
    seen: set[str] = set()
    out = []
    for block in blocks:
        lines = []
        for i in block.msg_ids:
            m = by_id[i]
            if i in seen or not m.content or is_sensitive(m.content):
                continue
            seen.add(i)
            lines.append(f"{m.author}: {m.content}")
        if lines:
            out.append("\n".join(lines)[:limit])
    return out


def merged_windows(blocks: Sequence[Block], by_id: dict[str, Message], order: dict[str, int]) -> list[str]:
    """Overlapping or touching windows become one continuous span."""
    ids = sorted({i for b in blocks for i in b.msg_ids}, key=lambda i: order[i])
    spans: list[list[str]] = []
    for i in ids:
        if spans and order[i] == order[spans[-1][-1]] + 1:
            spans[-1].append(i)
        else:
            spans.append([i])
    out = []
    for span in spans:
        lines = [f"{by_id[i].author}: {by_id[i].content}" for i in span
                 if by_id[i].content and not is_sensitive(by_id[i].content)]
        if lines:
            out.append("\n".join(lines))
    return out


def injected_messages(blocks: Sequence[Block]) -> int:
    return len({i for b in blocks for i in b.msg_ids})
