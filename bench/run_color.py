"""Color a contiguous part of a DEV group. Sends sanitized text to the configured model."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from bench import coloring, realdata
from bench import usage
from bench.llm import DEFAULT_MODEL, BatchLLM
from bench.sanitize import Sanitizer
from bench.schema import Visibility
from bench.tasks.real_tasks import clean_messages


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--limit-batches", type=int, default=0)
    args = ap.parse_args()
    if realdata.splits()[args.group] is not Visibility.DEV:
        raise SystemExit("coloring sends data out and is DEV only here")

    raw = realdata.load_group(args.group)
    messages = clean_messages(raw)
    san = Sanitizer(raw)
    usable_end = None
    if args.limit_batches:
        parts = coloring.batches(messages, 150, 20)[: args.limit_batches]
        usable_end = parts[-1][-1].timestamp
        messages = [m for m in messages if m.timestamp <= usable_end]
    llm = BatchLLM(args.out / f"color.{args.model}.cache.jsonl", args.model)
    colors, stats = coloring.color_group(messages, san, llm)
    stats["tokens"] = llm.tokens
    stats["model"] = args.model
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"colors.{args.model}.jsonl").write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in colors), encoding="utf-8"
    )
    (args.out / f"colors.{args.model}.stats.json").write_text(json.dumps(stats, indent=1), encoding="utf-8")
    usage.write(args.out / "usage.color.json", "上色")
    print(json.dumps(stats))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
