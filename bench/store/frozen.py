"""The frozen retrieval version (bench.frozen.FROZEN) fed from the store instead of the research files.

Per coloured group the same things are built as in the experiments: the imported messages with
people replaced by aliases and links and numbers masked, the colours of the frozen colour file,
the words learned from the first 70% of the messages, two keyword and two vector indexes.
Document vectors come from the `embedding` table; only a new question is sent to the embedding
service. A question is put through the group's alias table first, because the indexes hold
aliases, and the result is shown with the names and text as written.

    python -m bench.store.frozen vectors --db DB --groups 4fe395=runs/real-dev   # copy vectors from the cache file
    python -m bench.store.frozen check   --db DB --groups 4fe395=runs/real-dev   # same blocks as the recorded run
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sqlite3
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from bench.embed import AliyunEmbedder
from bench.frozen import FROZEN, cache_file
from bench.memory_text import new_messages
from bench.retrievers import frozen_pipeline as fp
from bench.sanitize import Sanitizer
from bench.schema import Message
from bench.store import online
from bench.store.importer import connect

log = logging.getLogger(__name__)
RECORDED = "raw/embed_qa_B/K5V2B_rrf4_at1500.jsonl"   # the answer-level run of the frozen version


def vectors_in_file(path: Path, keys: set[str]) -> dict[str, np.ndarray]:
    out = {}
    with path.open(encoding="utf-8") as f:
        for row in f:
            if row[9:73] in keys:   # {"key": "<64 hex>", ...
                out[row[9:73]] = np.array(json.loads(row)["v"], dtype=np.float32)
    return out


class StoreEmbedder(AliyunEmbedder):
    """Same keys and vectors as the research cache files, kept in the database.

    Document vectors are read from the table. Missing ones are taken from `cache_file` when given
    and stored; they are never requested here, so starting the bot cannot spend a re-embedding by
    accident. Question vectors are requested when needed and kept in memory only.
    """

    tries, first_delay, timeout = 2, 1.0, 15   # a question in a live turn does not wait long

    def __init__(self, con: sqlite3.Connection, config: dict = FROZEN, cache_file: Path | None = None, fetch: bool = False):
        e = config["embedding"]
        self.con, self.cache_file = con, cache_file
        # fetch: missing document vectors are requested and kept in `fetched`, not stored (the colouring job after
        # going live, bench/store/online.py, stores them with its run)
        self.fetch, self.fetched = fetch, {}
        self.model, self.dim, self.asymmetric, self.instruct = e["model"], e["dim"], e["asymmetric"], e["instruct"]
        self.last_tokens: list[int] = []
        self.asked: dict[str, np.ndarray] = {}
        self.offline = False
        self.copied = self.spent = 0

    def _documents(self, keys: list[str], texts) -> dict[str, np.ndarray]:
        have, want = {k: self.fetched[k] for k in keys if k in self.fetched}, sorted(set(keys) - set(self.fetched))
        for i in range(0, len(want), 500):
            part = want[i : i + 500]
            for k, blob in self.con.execute(f"SELECT key, vector FROM embedding WHERE key IN ({','.join('?' * len(part))})", part):
                have[k] = np.frombuffer(blob, dtype="<f4")
        missing = set(want) - set(have)
        if missing and self.cache_file:
            found = vectors_in_file(self.cache_file, missing)
            with self.con:
                self.con.executemany("INSERT OR IGNORE INTO embedding VALUES (?, ?, ?)",
                                     [(k, self.model, v.astype("<f4").tobytes()) for k, v in found.items()])
            self.copied += len(found)
            have.update(found)
            missing -= set(found)
        if missing and self.fetch:
            todo = sorted({(k, t) for k, t in zip(keys, texts) if k in missing})
            for i in range(0, len(todo), self.batch):
                part = todo[i : i + self.batch]
                vectors = self._request([t for _, t in part], "RETRIEVAL_DOCUMENT")
                self.spent += sum(self.last_tokens)
                for (k, _), v in zip(part, vectors):
                    have[k] = self.fetched[k] = np.array(v, dtype=np.float32)
            missing = set()
        if missing:
            raise RuntimeError(f"{len(missing)} document vectors are not in the store (run `python -m bench.store.frozen vectors`)")
        return have

    def _questions(self, keys: list[str], texts) -> dict[str, np.ndarray]:
        got = {k: v for k in keys if (v := self.asked.get(k)) is not None}
        missing = sorted({(k, t) for k, t in zip(keys, texts) if k not in got})
        if missing and self.offline:
            raise RuntimeError("question vector missing while offline")
        for i in range(0, len(missing), self.batch):
            part = missing[i : i + self.batch]
            vectors = self._request([t for _, t in part], "RETRIEVAL_QUERY")
            self.spent += sum(self.last_tokens)
            if len(self.asked) > 500:
                self.asked.clear()
            for (k, _), v in zip(part, vectors):
                got[k] = self.asked[k] = np.array([round(x, 5) for x in v], dtype=np.float32)
        return got

    def embed(self, texts, task: str, role: str = "向量") -> np.ndarray:
        keys = [self._key(t, task) for t in texts]
        have = self._questions(keys, texts) if task == "RETRIEVAL_QUERY" else self._documents(keys, texts)
        arr = np.array([have[k] for k in keys], dtype=np.float32)
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        return arr / np.where(norms == 0, 1, norms)


@dataclass
class GroupMemory:
    code: str
    retriever: fp.FrozenRetriever
    san: Sanitizer
    written: dict[str, Message]   # the messages as written (media placeholders removed), to show a result
    end_ts: float                 # time of the last message the colours cover

    def recall(self, query: str, as_of: float = math.inf, vectors: bool = True) -> list[list[Message]]:
        """The frozen result: per injected block, the messages the frozen feed shows, as written.

        The feed cuts a block at 1500 characters of its alias form; a message that starts before the cut is shown whole.
        """
        r = self.retriever if vectors else replace(self.retriever, indexes=self.retriever.indexes[:2])
        out = []
        for part in new_messages(r.retrieve(self.san.text(query), as_of), r.by_id):
            kept, used = [], 0
            for m in part:
                if used >= 1500:
                    break
                kept.append(self.written[m.msg_id])
                used += len(f"{m.author}: {m.content}") + 1
            if kept:
                out.append(kept)
        return out


def coloured(con: sqlite3.Connection, config: dict = FROZEN) -> dict[str, int]:
    """Chat code -> its newest colour run, for chats with the frozen colours or colours made after going live."""
    return dict(con.execute(
        "SELECT c.code, max(r.id) FROM color_run r JOIN chat c ON c.id = r.chat_id WHERE r.source_file = ? OR r.source_file LIKE ? "
        "GROUP BY c.code ORDER BY c.code", (config["colors"], online.ONLINE + "%")))


def load(con: sqlite3.Connection, code: str, embedder, config: dict = FROZEN, h: online.History | None = None) -> GroupMemory:
    """The frozen retriever over a chat's coloured history (bench/store/online.py): the imported export with the frozen
    colours, then the runs coloured after going live. Messages recorded later and not coloured yet are left out, so the
    learned words and the batches stay the ones the frozen colours were made with. h: a history already built."""
    from bench import chunking, tokenize
    from bench.retrievers.bm25 import BM25
    from bench.run_abcd import color_indexes

    h = h or online.history(con, code, config)
    if h.frozen:   # learned words from the first 70% of the export, as in the experiments
        ctx = SimpleNamespace(**color_indexes(h.frozen_messages, h.frozen_colors))
    else:
        ctx = SimpleNamespace(tok=tokenize.make_jieba(()))
    if not h.frozen or len(h.colors) != len(h.frozen_colors):
        ctx.summary_blocks = chunking.from_colors(h.messages, h.colors, "summary")
        ctx.raw_color_blocks = chunking.from_colors(h.messages, h.colors, "raw")
        ctx.by_color = {b.block_id: b for b in ctx.raw_color_blocks}
        ctx.summary_of = {b.block_id: b.index_text for b in ctx.summary_blocks}
        ctx.summary_index, ctx.raw_index = BM25(ctx.summary_blocks, ctx.tok), BM25(ctx.raw_color_blocks, ctx.tok)
    ctx.messages, ctx.by_id, ctx.channel = h.messages, {m.msg_id: m for m in h.messages}, code
    retriever, _ = fp.build(ctx, config, embedder, h.colors, h.batches)
    covered = {i for c in h.colors for i in c["msg_ids"]}
    return GroupMemory(code, retriever, h.san, {m.msg_id: m for m in h.clean}, max(ctx.by_id[i].timestamp for i in covered))


class FrozenMemory:
    """Every coloured chat's frozen retriever over one database file, built on first use and rebuilt for a chat
    when a new colour run of it shows up (colouring after going live)."""

    def __init__(self, db: Path, config: dict = FROZEN):
        self.db, self.config, self.lock = Path(db), config, threading.Lock()
        self.groups: dict[str, GroupMemory] | None = None
        self.built: dict[str, int] = {}   # chat code -> the newest run its retriever includes

    def _build(self, con: sqlite3.Connection, emb, code: str) -> GroupMemory | None:
        try:
            return load(con, code, emb, self.config)
        except (RuntimeError, KeyError, ValueError) as e:   # e.g. a vector the colouring job did not store
            log.warning("recall for %s built from its frozen colours only: %s", code, e)
        h = online.history(con, code, self.config, online=False)
        return load(con, code, emb, self.config, h) if h.frozen else None

    def load(self, refresh: bool = False) -> dict[str, GroupMemory]:
        with self.lock:
            if self.groups is not None and not refresh:
                return self.groups
            con = sqlite3.connect(self.db, timeout=30)
            try:
                emb = StoreEmbedder(con, self.config)
                runs = coloured(con, self.config)
                groups = dict(self.groups or {})
                for code, newest in runs.items():
                    if self.built.get(code) != newest:
                        g = self._build(con, emb, code)
                        if g is not None:
                            groups[code] = g
                        self.built[code] = newest
                self.groups = groups
            finally:
                con.close()   # questions do not need it
            return self.groups

    def search(self, query: str, as_of: float = math.inf, only: tuple[str, ...] = (), exclude: tuple[str, ...] = ()) -> tuple[dict, bool]:
        """Group code -> its frozen result. The flag is False when no question vector could be had and only the keyword routes ran.
        Runs off the event loop, so it is also where chats coloured since the last call are rebuilt."""
        groups = [g for code, g in self.load(refresh=True).items() if code not in exclude and (not only or code in only)]
        try:
            return {g.code: g.recall(query, as_of) for g in groups}, True
        except (RuntimeError, OSError):
            return {g.code: g.recall(query, as_of, vectors=False) for g in groups}, False


def check(con: sqlite3.Connection, code: str, run_dir: Path, config: dict = FROZEN) -> dict:
    """The store-fed retriever must return the blocks and the injected text the recorded run of the frozen version got."""
    rows = [json.loads(x) for x in (run_dir / RECORDED).open(encoding="utf-8")]
    emb = StoreEmbedder(con, config)
    emb.offline = True
    t0 = time.time()
    g = load(con, code, emb, config, online.history(con, code, config, online=False))   # the recorded run knew no later colours
    built = round(time.time() - t0, 1)
    emb.asked = vectors_in_file(cache_file(config, run_dir), {emb._key(x["question"], "RETRIEVAL_QUERY") for x in rows})
    blocks = text = aliased = 0
    for x in rows:
        got = g.retriever.retrieve(x["question"], x["as_of"])
        blocks += [b.block_id for b in got] == x["retrieved"]
        text += g.retriever.feed(got) == x["injected"]
        aliased += g.san.text(x["question"]) != x["question"]
    shown = g.recall(rows[0]["question"], rows[0]["as_of"])
    return {"rows": len(rows), "same_blocks": blocks, "same_injected_text": text, "build_seconds": built,
            "questions_changed_by_alias_table": aliased, "first_row_blocks_shown": len(shown),
            "passed": blocks == text == len(rows)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("vectors", "check"))
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--groups", nargs="+", required=True, help="code=run folder, e.g. 4fe395=runs/real-dev")
    args = ap.parse_args()
    con, out = connect(args.db), {}
    for code, folder in (g.split("=", 1) for g in args.groups):
        if args.cmd == "check":
            out[code] = check(con, code, Path(folder))
            continue
        emb = StoreEmbedder(con, FROZEN, cache_file(FROZEN, Path(folder)))
        load(con, code, emb, FROZEN, online.history(con, code, FROZEN, online=False))
        out[code] = {"copied": emb.copied, "stored": con.execute("SELECT count(*) FROM embedding").fetchone()[0]}
    print(json.dumps(out, ensure_ascii=False))
    return 0 if all(r.get("passed", True) for r in out.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
