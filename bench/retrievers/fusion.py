"""Reciprocal rank fusion over retrievers that share block ids (option I6)."""
from __future__ import annotations

from collections.abc import Sequence

from bench.retrievers.bm25 import BM25
from bench.schema import Block

RRF_K = 60


def rrf(indexes: Sequence[BM25], blocks_by_id: dict[str, Block], query: str, as_of: float, k: int,
        channel: str = "", depth: int = 30) -> list[tuple[Block, float]]:
    scores: dict[str, float] = {}
    for index in indexes:
        for rank, (block, _) in enumerate(index.search(query, as_of, depth, channel), 1):
            scores[block.block_id] = scores.get(block.block_id, 0.0) + 1.0 / (RRF_K + rank)
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:k]
    return [(blocks_by_id[i], s) for i, s in ranked]


def quota(indexes: Sequence, blocks_by_id: dict[str, Block], query: str, as_of: float, k: int,
          channel: str = "", per_route: int = 3, depth: int = 30) -> list[tuple[Block, float]]:
    """Each route first places its own top few, then RRF fills the rest."""
    ranked = rrf(indexes, blocks_by_id, query, as_of, depth, channel, depth)
    taken: list[str] = []
    for index in indexes:
        for block, _ in index.search(query, as_of, per_route, channel):
            if block.block_id not in taken:
                taken.append(block.block_id)
    for block, _ in ranked:
        if len(taken) >= k:
            break
        if block.block_id not in taken:
            taken.append(block.block_id)
    score = {b.block_id: s for b, s in ranked}
    return [(blocks_by_id[i], score.get(i, 0.0)) for i in taken[:k]]
