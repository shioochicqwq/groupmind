"""Minimal event organisation over B blocks, no model calls.

Levels:
  episode   a stretch of chat between silences of at least `gap` seconds (the baseline
            segmenter; nothing about topics). One episode can hold several parallel threads.
  thread    within an episode, local blocks that continue the same context. v0 links blocks
            that adjacent coloring batches made of the same overlap (the merged-v1 rule, here
            used only as a link, never to rebuild retrieval blocks); v1 also links blocks whose
            summary vectors are close (cosine >= tau) and that overlap or touch in time.
  links     episodes on different days whose threads are close (a topic picked up again);
            stored as relations, not merged.

Every object keeps its scope and points back to block ids and message ids.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field

from bench.color_fix import merge_overlaps
from bench.schema import Message

VERSION = "events-v0"


@dataclass
class Thread:
    thread_id: str
    block_ids: list[str]
    start_ts: float
    end_ts: float
    n_msgs: int


@dataclass
class Episode:
    event_id: str
    scope: str
    start_ts: float
    end_ts: float
    first_msg: str
    last_msg: str
    n_msgs: int
    block_refs: list[dict]          # {block_id, share, first_msg, last_msg, n_in_episode}
    threads: list[Thread] = field(default_factory=list)
    features: dict = field(default_factory=dict)
    impressions: list[dict] = field(default_factory=list)   # typed, with evidence refs; empty in v0
    version: str = VERSION


def episodes_by_gap(messages: Sequence[Message], gap: float) -> list[list[Message]]:
    out: list[list[Message]] = []
    for m in sorted(messages, key=lambda m: (m.timestamp, m.msg_id)):
        if out and m.timestamp - out[-1][-1].timestamp < gap:
            out[-1].append(m)
        else:
            out.append([m])
    return out


def primary_color(colors: list[dict]) -> dict[str, str]:
    """Each message's colour in the B index: the first (earliest batch) colour that keeps it."""
    out: dict[str, str] = {}
    for c in colors:
        for i in c["msg_ids"]:
            out.setdefault(i, c["color_id"])
    return out


def _union(pairs: list[tuple[str, str]], items: list[str]) -> list[list[str]]:
    parent = {x: x for x in items}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in pairs:
        if a in parent and b in parent:
            parent[find(a)] = find(b)
    groups: dict[str, list[str]] = defaultdict(list)
    for x in items:
        groups[find(x)].append(x)
    return list(groups.values())


def overlap_links(colors: list[dict], batches: list[list]) -> list[tuple[str, str]]:
    merged, _ = merge_overlaps(colors, batches)
    pairs = []
    for c in merged:
        ids = c.get("merged_from", [])
        pairs += [(ids[0], x) for x in ids[1:]]
    return pairs


def build(group: str, messages: Sequence[Message], colors: list[dict], batches: list[list], gap: float = 1800,
          min_msgs: int = 20, vectors: dict[str, list[float]] | None = None, tau: float = 0.0) -> list[Episode]:
    """vectors: colour id -> normalised summary vector (only needed when tau > 0)."""
    span = {}
    by_id = {m.msg_id: m for m in messages}
    for c in colors:
        ts = [by_id[i].timestamp for i in c["msg_ids"] if i in by_id]
        if ts:
            span[c["color_id"]] = (min(ts), max(ts))
    color_of = primary_color(colors)
    links = overlap_links(colors, batches)
    out = []
    for k, part in enumerate(episodes_by_gap(messages, gap)):
        if len(part) < min_msgs:
            continue
        counts = Counter(color_of[m.msg_id] for m in part if m.msg_id in color_of)
        refs = []
        for cid, n in sorted(counts.items(), key=lambda kv: span[kv[0]]):
            ids = [m.msg_id for m in part if color_of.get(m.msg_id) == cid]
            refs.append({"block_id": cid, "n_in_episode": n, "first_msg": ids[0], "last_msg": ids[-1]})
        bids = [r["block_id"] for r in refs]
        pairs = [p for p in links if p[0] in counts and p[1] in counts]
        if tau > 0 and vectors:
            for i, a in enumerate(bids):
                for b in bids[i + 1:]:
                    if a in vectors and b in vectors and _touch(span[a], span[b]) and _cos(vectors[a], vectors[b]) >= tau:
                        pairs.append((a, b))
        threads = []
        for j, g in enumerate(sorted(_union(pairs, bids), key=lambda g: min(span[x][0] for x in g))):
            threads.append(Thread(f"{group}:E{k}:T{j}", sorted(g, key=lambda x: span[x]),
                                  min(span[x][0] for x in g), max(span[x][1] for x in g), sum(counts[x] for x in g)))
        ep = Episode(f"{group}:E{k}", f"group:{group}", part[0].timestamp, part[-1].timestamp, part[0].msg_id,
                     part[-1].msg_id, len(part), refs, threads)
        thread_of = {b: t.thread_id for t in threads for b in t.block_ids}
        ep.features = features(part, color_of, thread_of)
        out.append(ep)
    return out


def _touch(a: tuple[float, float], b: tuple[float, float], slack: float = 600) -> bool:
    return a[0] <= b[1] + slack and b[0] <= a[1] + slack


def _cos(a, b) -> float:
    return float(sum(x * y for x, y in zip(a, b)))


def features(part: Sequence[Message], color_of: dict[str, str], thread_of: dict[str, str]) -> dict:
    """Structural features only; nothing here claims to know how anyone felt."""
    n = len(part)
    minutes = max((part[-1].timestamp - part[0].timestamp) / 60, 1.0)
    speakers = Counter(m.author for m in part)
    p = [c / n for c in speakers.values()]
    entropy = -sum(x * math.log(x) for x in p) / math.log(len(p)) if len(p) > 1 else 0.0
    switches = sum(a.author != b.author for a, b in zip(part, part[1:]))
    seq = [thread_of.get(color_of.get(m.msg_id, ""), "") for m in part]
    seq = [s for s in seq if s]
    interleave = sum(a != b for a, b in zip(seq, seq[1:])) / max(len(seq) - 1, 1)
    # Parallel threads: per 10-minute window, how many threads have a message in it.
    windows: dict[int, set[str]] = defaultdict(set)
    for m in part:
        t = thread_of.get(color_of.get(m.msg_id, ""))
        if t:
            windows[int(m.timestamp // 600)].add(t)
    par = [len(v) for v in windows.values()] or [0]
    per_min = Counter(int(m.timestamp // 60) for m in part)
    return {
        "n_msgs": n, "minutes": round(minutes, 1), "rate_per_min": round(n / minutes, 3),
        "peak_per_min": max(per_min.values()),
        "speakers": len(speakers), "speaker_entropy": round(entropy, 3),
        "turn_switch_rate": round(switches / max(n - 1, 1), 3),
        "reply_share": round(sum(bool(m.reply_to) for m in part) / n, 3),
        "media_share": round(sum(bool(m.media) for m in part) / n, 3),
        "mention_share": round(sum("@" in m.content for m in part) / n, 3),
        "threads": len(set(seq)), "colored_share": round(len(seq) / n, 3),
        "thread_interleave": round(interleave, 3),
        "parallel_threads_mean": round(sum(par) / len(par), 2), "parallel_threads_max": max(par),
    }


def to_json(ep: Episode) -> dict:
    return {
        "event_id": ep.event_id, "scope": ep.scope, "intervals": [{"start": ep.start_ts, "end": ep.end_ts}],
        "source_refs": ep.block_refs, "first_msg": ep.first_msg, "last_msg": ep.last_msg, "n_msgs": ep.n_msgs,
        "subevents": [vars(t) for t in ep.threads], "features": ep.features, "impressions": ep.impressions,
        "version": ep.version,
    }
