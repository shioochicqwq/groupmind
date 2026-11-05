"""SQLite FTS5 index over blocks, for comparing with the in-memory BM25 (M4).

Chinese is pre-segmented with the same tokenizer as BM25 and stored as space-separated terms,
so FTS5 only sees whitespace tokens. Two ways to rank:

- "native":  FTS5's own bm25() (k1=1.2, b=0.75, its own IDF), ordered by rank.
- "rescore": FTS5 only finds the candidates (blocks matching any query term); they are then
             scored with exactly the formula and corpus statistics of bench.retrievers.bm25.BM25.
"""
from __future__ import annotations

import sqlite3
from collections import Counter
from collections.abc import Callable, Sequence

from bench.retrievers.bm25 import BM25
from bench.schema import Block


def _quote(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


class FTS5Index:
    def __init__(self, blocks: Sequence[Block], tokenizer: Callable[[str], list[str]], mode: str = "native",
                 path: str = ":memory:"):
        if mode not in ("native", "rescore"):
            raise ValueError(mode)
        self.blocks, self.tokenizer, self.mode = list(blocks), tokenizer, mode
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS blk USING fts5(body, end_ts UNINDEXED, channel UNINDEXED, "
                        "tokenize = \"unicode61 remove_diacritics 0 tokenchars '_'\")")
        self.db.executemany("INSERT INTO blk(rowid, body, end_ts, channel) VALUES (?, ?, ?, ?)",
                            [(i, " ".join(tokenizer(b.index_text)), b.end_ts, b.channel) for i, b in enumerate(self.blocks)])
        self.db.commit()
        self.bm25 = BM25(self.blocks, tokenizer) if mode == "rescore" else None
        if self.bm25:
            self.tf = [Counter(tokenizer(b.index_text)) for b in self.blocks]

    def _candidates(self, terms: list[str], as_of: float, channel: str) -> list[tuple[int, float]]:
        sql = "SELECT rowid, bm25(blk) FROM blk WHERE blk MATCH ? AND end_ts < ?"
        params: list = [" OR ".join(_quote(t) for t in dict.fromkeys(terms)), as_of]
        if channel:
            sql += " AND channel = ?"
            params.append(channel)
        return self.db.execute(sql, params).fetchall()

    def search(self, query: str, as_of: float, k: int, channel: str = "") -> list[tuple[Block, float]]:
        terms = [t for t in self.tokenizer(query) if t.strip()]
        if not terms:
            return []
        rows = self._candidates(terms, as_of, channel)
        if self.mode == "native":
            # FTS5 scores are negative, smaller is better; flip the sign so larger is better.
            ranked = sorted(((i, -s) for i, s in rows), key=lambda x: (-x[1], x[0]))[:k]
            return [(self.blocks[i], s) for i, s in ranked]
        bm = self.bm25
        scored = []
        for i, _ in rows:
            s = 0.0
            for term in terms:  # repeated query terms count again, as in BM25Okapi
                tf = self.tf[i].get(term, 0)
                if tf:
                    s += bm.idf[term] * tf * (bm.k1 + 1) / (tf + bm.norm[i])
            scored.append((i, s))
        ranked = sorted(scored, key=lambda x: (-x[1], x[0]))[:k]
        return [(self.blocks[i], s) for i, s in ranked if s > 0]
