"""Turn raw messages into retrievable blocks; a coloring is one such mapping."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence

from bench.schema import Block, Message


def by_channel(messages: Iterable[Message]) -> dict[str, list[Message]]:
    groups: dict[str, list[Message]] = defaultdict(list)
    for m in messages:
        groups[m.channel].append(m)
    for ms in groups.values():
        ms.sort(key=lambda m: (m.timestamp, m.msg_id))
    return groups


def single_message(messages: Iterable[Message]) -> list[Block]:
    return [Block(m.msg_id, (m.msg_id,), m.timestamp, m.channel, m.content) for m in messages if m.content]


def fixed_window(messages: Sequence[Message], size: int, stride: int) -> list[Block]:
    blocks = []
    for channel, ms in by_channel(messages).items():
        for start in range(0, max(len(ms) - size, 0) + stride, stride):
            part = ms[start : start + size]
            if not part:
                continue
            text = "\n".join(m.content for m in part if m.content)
            blocks.append(
                Block(f"{channel}:{start}", tuple(m.msg_id for m in part), part[-1].timestamp, channel, text)
            )
    return blocks


def from_colors(messages: Sequence[Message], colors: Iterable[dict], index: str) -> list[Block]:
    """Colors are {color_id, msg_ids, summary, ...}; index is 'summary' or 'raw'."""
    by_id = {m.msg_id: m for m in messages}
    blocks = []
    for color in colors:
        part = sorted((by_id[i] for i in color["msg_ids"] if i in by_id), key=lambda m: (m.timestamp, m.msg_id))
        if not part:
            continue
        text = color.get("summary", "") if index == "summary" else "\n".join(m.content for m in part if m.content)
        blocks.append(
            Block(
                color["color_id"],
                tuple(m.msg_id for m in part),
                part[-1].timestamp,
                part[-1].channel,
                text,
                tuple(color.get("labels", ())),
            )
        )
    return blocks
