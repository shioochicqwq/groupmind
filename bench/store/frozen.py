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
import math
import sqlite3
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from bench import coloring
from bench.embed import AliyunEmbedder
from bench.frozen import FROZEN, cache_file
from bench.memory_text import new_messages
from bench.retrievers import frozen_pipeline as fp
from bench.sanitize import Sanitizer
from bench.schema import Message
from bench.store.importer import colors_from_db, connect, messages_from_db

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

    def __init__(self, con: sqlite3.Connection, config: dict = FROZEN, cache_file: Path | None = None):
        e = config["embedding"]
        self.con, self.cache_file = con, cache_file
        self.model, self.dim, self.asymmetric, self.instruct = e["model"], e["dim"], e["asymmetric"], e["instruct"]
        self.last_tokens: list[int] = []
        self.asked: dict[str, np.ndarray] = {}
        self.offline = False
        self.copied = self.spent = 0

    def _documents(self, keys: list[str]) -> dict[str, np.ndarray]:
        have, want = {}, sorted(set(keys))
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
        have = self._questions(keys, texts) if task == "RETRIEVAL_QUERY" else self._documents(keys)
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


def coloured(con: sqlite3.Connection, config: dict = FROZEN) -> list[str]:
    return [r[0] for r in con.execute(
        "SELECT c.code FROM color_run r JOIN chat c ON c.id = r.chat_id WHERE r.source_file = ? ORDER BY c.code", (config["colors"],))]


def load(con: sqlite3.Connection, code: str, embedder, config: dict = FROZEN) -> GroupMemory:
    from bench.run_abcd import color_indexes
    from bench.run_s0 import sanitized
    from bench.tasks.real_tasks import clean_messages

    # The research corpus is the imported export. Messages the bot recorded later in the same group are
    # left out, so the learned words and the batches stay the ones the frozen colours were made with.
    imported = {old for (old,) in con.execute("SELECT old_id FROM id_map WHERE kind = 'message' AND chat_code = ?", (code,))}
    raw = [m for m in messages_from_db(con, code) if m.msg_id in imported]
    size, overlap = con.execute("SELECT r.batch_size, r.overlap FROM color_run r JOIN chat c ON c.id = r.chat_id "
                                "WHERE c.code = ? AND r.source_file = ?", (code, config["colors"])).fetchone()
    san, clean = Sanitizer(raw), clean_messages(raw)
    messages = sanitized(clean, san)
    colors = colors_from_db(con, code, config["colors"])
    ctx = SimpleNamespace(messages=messages, by_id={m.msg_id: m for m in messages}, channel=code, **color_indexes(messages, colors))
    retriever, _ = fp.build(ctx, config, embedder, colors, coloring.batches(clean, size, overlap))
    covered = {i for c in colors for i in c["msg_ids"]}
    return GroupMemory(code, retriever, san, {m.msg_id: m for m in clean}, max(ctx.by_id[i].timestamp for i in covered))


class FrozenMemory:
    """Every coloured group's frozen retriever over one database file, built on first use."""

    def __init__(self, db: Path, config: dict = FROZEN):
        self.db, self.config, self.lock = Path(db), config, threading.Lock()
        self.groups: dict[str, GroupMemory] | None = None

    def load(self) -> dict[str, GroupMemory]:
        with self.lock:
            if self.groups is None:
                con = sqlite3.connect(self.db, timeout=30)
                try:
                    emb = StoreEmbedder(con, self.config)
                    self.groups = {code: load(con, code, emb, self.config) for code in coloured(con, self.config)}
                finally:
                    con.close()   # questions do not need it
            return self.groups

    def search(self, query: str, as_of: float = math.inf, only: tuple[str, ...] = (), exclude: tuple[str, ...] = ()) -> tuple[dict, bool]:
        """Group code -> its frozen result. The flag is False when no question vector could be had and only the keyword routes ran."""
        groups = [g for code, g in self.load().items() if code not in exclude and (not only or code in only)]
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
    g = load(con, code, emb, config)
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
        load(con, code, emb)
        out[code] = {"copied": emb.copied, "stored": con.execute("SELECT count(*) FROM embedding").fetchone()[0]}
    print(json.dumps(out, ensure_ascii=False))
    return 0 if all(r.get("passed", True) for r in out.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
