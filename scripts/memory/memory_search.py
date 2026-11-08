"""Read-only memory retrieval for the DSH memory-test session.

Data: qqbot-data/store/memory.db (SQLite, all non-FROZEN groups). Messages stay
original; this tool only reads and returns excerpts with group code, time
(UTC+8) and sender. It never writes back to the store.

Subcommands (stdout is JSON):
  catalog                 groups with message counts and time ranges
  recent [--count N]      tail of the most recently active group
  search --query Q [...]  BM25 over messages, hits plus two neighbours each

The BM25 index is cached under ~/.cache/qqbot-memory-bm25/ and rebuilt when the
database changes, because tokenising ~93k messages takes tens of seconds.
"""

from __future__ import annotations

import argparse
import json
import pickle
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT.parent / "qqbot-data" / "store" / "memory.db"
CACHE_DIR = Path.home() / ".cache" / "qqbot-memory-bm25"
TZ = timezone(timedelta(hours=8))

sys.path.insert(0, str(ROOT))
from bench.retrievers.bm25 import BM25  # noqa: E402
from bench.schema import Block  # noqa: E402
from bench.tokenize import make_jieba  # noqa: E402


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, TZ).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def catalog(con) -> dict:
    rows = con.execute(
        "SELECT c.code, count(*) AS n, min(m.ts) AS first, max(m.ts) AS last, "
        "count(DISTINCT m.sender_id) AS people "
        "FROM message m JOIN chat c ON c.id = m.chat_id GROUP BY c.code ORDER BY last DESC"
    ).fetchall()
    return {
        "groups": [
            {"code": r["code"], "messages": r["n"], "first": iso(r["first"]), "last": iso(r["last"]), "people": r["people"]}
            for r in rows
        ],
        "now": iso(max(r["last"] for r in rows)),
    }


def recent(con, count: int) -> dict:
    last = con.execute(
        "SELECT c.code, max(m.ts) AS last, c.id AS chat_id FROM message m JOIN chat c ON c.id = m.chat_id "
        "GROUP BY c.id ORDER BY last DESC LIMIT 1"
    ).fetchone()
    if last is None:
        return {"status": "empty"}
    rows = con.execute(
        "SELECT m.ts, m.text, m.media, m.nickname_at_time AS name, p.platform_uid AS uid "
        "FROM message m JOIN person p ON p.id = m.sender_id "
        "WHERE m.chat_id = ? ORDER BY m.order_key DESC LIMIT ?",
        (last["chat_id"], count),
    ).fetchall()
    messages = [
        {"time": iso(r["ts"]), "sender": r["name"] or r["uid"], "text": r["text"],
         **({"media": r["media"]} if r["media"] and r["media"] != "[]" else {})}
        for r in reversed(rows)
    ]
    return {"status": "ok", "chat": last["code"], "now": iso(last["last"]), "messages": messages}


def _restore(state: dict) -> BM25:
    """Rebuild BM25 from pickled data; the tokenizer closure itself is not picklable."""
    index = BM25.__new__(BM25)
    index.blocks = state["blocks"]
    index.tokenizer = make_jieba()
    index.postings = state["postings"]
    index.avgdl = state["avgdl"]
    index.norm = state["norm"]
    index.idf = state["idf"]
    return index


def load_index(con) -> tuple[BM25, list[dict]]:
    stamp = CACHE_DIR / "stamp.json"
    db_mtime = DB.stat().st_mtime
    if stamp.exists():
        meta = json.loads(stamp.read_text(encoding="utf-8"))
        if meta.get("db_mtime") == db_mtime:
            with (CACHE_DIR / "index.pkl").open("rb") as f:
                state, msgs = pickle.load(f)
            return _restore(state), msgs
    rows = con.execute(
        "SELECT m.id, c.code AS chat, m.ts, m.order_key, m.text, m.media, "
        "m.nickname_at_time AS name, p.platform_uid AS uid "
        "FROM message m JOIN chat c ON c.id = m.chat_id JOIN person p ON p.id = m.sender_id "
        "ORDER BY m.chat_id, m.order_key"
    ).fetchall()
    msgs = [
        {"id": r["id"], "chat": r["chat"], "ts": r["ts"], "text": r["text"], "media": r["media"],
         "name": r["name"] or r["uid"]}
        for r in rows
    ]
    tokenize = make_jieba()
    blocks = [
        Block(block_id=str(m["id"]), msg_ids=(str(m["id"]),), end_ts=m["ts"], channel=m["chat"],
              index_text=m["text"])
        for m in msgs
    ]
    index = BM25(blocks, tokenize)
    state = {"blocks": blocks, "postings": dict(index.postings), "avgdl": index.avgdl,
             "norm": index.norm, "idf": index.idf}
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with (CACHE_DIR / "index.pkl").open("wb") as f:
        pickle.dump((state, msgs), f)
    stamp.write_text(json.dumps({"db_mtime": db_mtime, "built": datetime.now(TZ).isoformat(timespec="seconds")}), encoding="utf-8")
    return _restore(state), msgs


def search(con, query: str, limit: int, as_of: str | None, groups: list[str] | None) -> dict:
    index, msgs = load_index(con)
    as_ts = datetime.fromisoformat(as_of).timestamp() if as_of else float("inf")
    by_id = {m["id"]: m for m in msgs}
    channels = ", ".join(groups) if groups else "all"
    hits = index.search(query, as_ts, limit * 3)
    related = []
    for block, score in hits:
        msg = by_id[int(block.block_id)]
        if groups and msg["chat"] not in groups:
            continue
        related.append({"id": msg["id"], "chat": msg["chat"], "time": iso(msg["ts"]),
                        "sender": msg["name"], "text": msg["text"], "score": round(score, 3),
                        **({"media": msg["media"]} if msg["media"] and msg["media"] != "[]" else {})})
        if len(related) >= limit:
            break
    if not related:
        return {"status": "empty", "query": query, "channels": channels, "hits": []}
    # Two neighbours on each side, inside the same group.
    con2 = connect()
    context = []
    for hit in related:
        rows = con2.execute(
            "SELECT m.ts, m.text, m.nickname_at_time AS name FROM message m "
            "WHERE m.chat_id = (SELECT chat_id FROM message WHERE id = ?) "
            "AND m.order_key BETWEEN (SELECT order_key FROM message WHERE id = ?) - 2 "
            "AND (SELECT order_key FROM message WHERE id = ?) + 2 ORDER BY m.order_key",
            (hit["id"], hit["id"], hit["id"]),
        ).fetchall()
        context.append([{"time": iso(r["ts"]), "sender": r["name"] or "?", "text": r["text"]} for r in rows])
    con2.close()
    return {"status": "ok", "query": query, "channels": channels, "hits": related, "context": context}


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("catalog")
    recent_p = sub.add_parser("recent")
    recent_p.add_argument("--count", type=int, default=40)
    search_p = sub.add_parser("search")
    search_p.add_argument("--query", required=True)
    search_p.add_argument("--limit", type=int, default=6)
    search_p.add_argument("--as-of", default="")
    search_p.add_argument("--groups", default="")
    args = ap.parse_args()
    con = connect()
    try:
        if args.cmd == "catalog":
            out = catalog(con)
        elif args.cmd == "recent":
            out = recent(con, max(1, min(args.count, 200)))
        else:
            groups = [g.strip() for g in args.groups.split(",") if g.strip()] or None
            out = search(con, args.query.strip(), max(1, min(args.limit, 20)), args.as_of.strip() or None, groups)
    finally:
        con.close()
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
