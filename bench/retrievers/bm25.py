"""BM25Okapi over blocks, with time visibility applied before ranking."""
from __future__ import annotations

import heapq
import math
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence

from bench.schema import Block


class BM25:
    # Same constants as rank_bm25.BM25Okapi, which GroupMemBench's baseline uses.
    k1 = 1.5
    b = 0.75
    epsilon = 0.25

    def __init__(self, blocks: Sequence[Block], tokenizer: Callable[[str], list[str]]):
        self.blocks = list(blocks)
        self.tokenizer = tokenizer
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        lengths = []
        for i, block in enumerate(self.blocks):
            counts = Counter(tokenizer(block.index_text))
            lengths.append(sum(counts.values()))
            for term, tf in counts.items():
                self.postings[term].append((i, tf))
        n = max(len(self.blocks), 1)
        self.avgdl = sum(lengths) / n
        self.norm = [self.k1 * (1 - self.b + self.b * dl / self.avgdl) if self.avgdl else self.k1 for dl in lengths]
        idf = {t: math.log(n - len(p) + 0.5) - math.log(len(p) + 0.5) for t, p in self.postings.items()}
        floor = self.epsilon * (sum(idf.values()) / len(idf)) if idf else 0.0
        self.idf = {t: (v if v >= 0 else floor) for t, v in idf.items()}

    def search(self, query: str, as_of: float, k: int, channel: str = "") -> list[tuple[Block, float]]:
        scores: dict[int, float] = defaultdict(float)
        for term in self.tokenizer(query):
            idf = self.idf.get(term)
            if idf is None:
                continue
            for i, tf in self.postings[term]:
                block = self.blocks[i]
                if block.end_ts >= as_of or (channel and block.channel != channel):
                    continue
                scores[i] += idf * tf * (self.k1 + 1) / (tf + self.norm[i])
        top = heapq.nsmallest(k, scores.items(), key=lambda kv: (-kv[1], kv[0]))
        return [(self.blocks[i], s) for i, s in top if s > 0]
