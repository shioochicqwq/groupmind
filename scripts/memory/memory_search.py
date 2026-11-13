"""Command-line view of the message store, for looking at what the bot's memory tools would return.

The store and its keyword index live in bothost/store.py; the model reaches them through bothost/tools.py.
Subcommands (stdout is JSON):
  catalog                 groups with message counts and time ranges
  recent [--count N]      tail of the most recently active group
  search --query Q [...]  best-matching messages over all groups, two neighbours each side
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT.parent / "qqbot-data" / "store" / "memory.db"
sys.path.insert(0, str(ROOT))
from bothost.store import TZ, Store  # noqa: E402


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, TZ).isoformat(timespec="seconds")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DB)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("catalog")
    sub.add_parser("recent").add_argument("--count", type=int, default=40)
    search_p = sub.add_parser("search")
    search_p.add_argument("--query", required=True)
    search_p.add_argument("--limit", type=int, default=6)
    search_p.add_argument("--as-of", default="")
    search_p.add_argument("--groups", default="")
    args = ap.parse_args()
    store = Store(args.db)
    groups = [{**dict(g), "first": iso(g["first"]), "last": iso(g["last"])} for g in store.catalog()]
    if args.cmd == "catalog":
        out = {"groups": groups}
    elif args.cmd == "recent":
        rows = store.recent(groups[0]["code"], max(1, min(args.count, 200))) if groups else []
        out = {"chat": groups[0]["code"] if groups else "", "messages": [{"time": iso(r["ts"]), "sender": r["name"], "text": r["text"]} for r in rows]}
    else:
        only = tuple(g.strip() for g in args.groups.split(",") if g.strip())
        hits = store.search(args.query.strip(), max(1, min(args.limit, 20)), only,
                            datetime.fromisoformat(args.as_of).timestamp() if args.as_of.strip() else float("inf"))
        out = {"query": args.query, "hits": [{**h, "lines": [{**r, "ts": iso(r["ts"])} for r in h["lines"]]} for h in hits]}
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
