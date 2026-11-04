"""Recover question-writing usage for a past run by replaying it against the cache.

The segments come from the same seeds as the original runs, so every call should hit the
cache; any miss is a real new call and is recorded as new.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from bench import realdata, usage
from bench.llm import DEFAULT_MODEL, BatchLLM
from bench.run_s0 import render, sanitized
from bench.sanitize import Sanitizer
from bench.tasks import silver
from bench.tasks.real_tasks import clean_messages


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--batch", action="append", required=True, help="segments:seed:id_prefix, as in the original run")
    args = ap.parse_args()
    raw = realdata.load_group(args.group)
    messages = sanitized(clean_messages(raw), Sanitizer(raw))
    end_ts = messages[-1].timestamp + 1
    main_llm = BatchLLM(args.out / "s0.main.cache.jsonl", DEFAULT_MODEL)
    fast_llm = BatchLLM(args.out / "s0.fast.cache.jsonl", DEFAULT_MODEL)
    for spec in args.batch:
        n, seed, prefix = spec.split(":")
        segments = silver.sample_segments(messages, end_ts, int(n), 40, int(seed), 7 * 86400)
        _, stats = silver.build_questions(segments, render, main_llm, fast_llm, end_ts, id_prefix=prefix)
        print(prefix, stats)
    data = usage.write(args.out / "usage.questions.json", "出题和核题")
    print({r: (v["distinct"], v["new_calls"]) for r, v in data["by_role"].items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
