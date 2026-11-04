"""Turn several ranked routes into one injected set under a character budget (E1-E4).

Every packer measures what is actually injected: `feed` renders the chosen blocks with
repeated messages removed, so a block that adds nothing new costs nothing.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Sequence

from bench.schema import Block

RRF_K = 60
Feed = Callable[[list[Block]], list[str]]


def size(feed: Feed, blocks: list[Block]) -> int:
    return sum(len(t) for t in feed(blocks))


def rrf_scores(routes: Sequence[Sequence[Block]]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for route in routes:
        for rank, block in enumerate(route, 1):
            scores[block.block_id] = scores.get(block.block_id, 0.0) + 1.0 / (RRF_K + rank)
    return scores


def _by_id(routes: Sequence[Sequence[Block]]) -> dict[str, Block]:
    return {b.block_id: b for route in routes for b in route}


def global_rrf(routes: Sequence[Sequence[Block]]) -> list[Block]:
    """E1: one list by fused score."""
    scores, by_id = rrf_scores(routes), _by_id(routes)
    return [by_id[i] for i, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))]


def round_robin(routes: Sequence[Sequence[Block]]) -> list[Block]:
    """E2: first of every route, then second of every route, and so on."""
    out, seen = [], set()
    for depth in range(max((len(r) for r in routes), default=0)):
        for route in routes:
            if depth < len(route) and route[depth].block_id not in seen:
                seen.add(route[depth].block_id)
                out.append(route[depth])
    return out


def pack_in_order(order: Sequence[Block], feed: Feed, budget: int) -> list[Block]:
    """Strict packing: stop at the first block that does not fit."""
    taken: list[Block] = []
    for block in order:
        if size(feed, taken + [block]) > budget:
            break
        taken.append(block)
    return taken


def reserved(routes: Sequence[Sequence[Block]], feed: Feed, budget: int) -> list[Block]:
    """E3: each route fills its own share first; the rest goes to the best fused blocks that fit."""
    scores = rrf_scores(routes)
    share = budget // max(len(routes), 1)
    taken: list[Block] = []
    for route in routes:
        used = 0
        for block in route:
            if block in taken:
                continue
            extra = size(feed, taken + [block]) - size(feed, taken)
            if used + extra > share:
                continue
            taken.append(block)
            used += extra
    for block in global_rrf(routes):
        if block not in taken and size(feed, taken + [block]) <= budget:
            taken.append(block)
    return sorted(taken, key=lambda b: (-scores[b.block_id], b.block_id))


def budget_aware(routes: Sequence[Sequence[Block]], feed: Feed, budget: int) -> list[Block]:
    """E4: greedily add the block with the best fused score per square root of new characters."""
    scores = rrf_scores(routes)
    pool = list(_by_id(routes).values())
    taken: list[Block] = []
    current = 0
    while pool:
        best, best_value, best_size = None, -1.0, 0
        for block in pool:
            new_size = size(feed, taken + [block])
            extra = new_size - current
            if new_size > budget:
                continue
            value = scores[block.block_id] / math.sqrt(max(extra, 1)) if extra > 0 else 0.0
            if value > best_value:
                best, best_value, best_size = block, value, new_size
        if best is None or best_value <= 0:
            break
        taken.append(best)
        current = best_size
        pool.remove(best)
    return sorted(taken, key=lambda b: (-scores[b.block_id], b.block_id))
