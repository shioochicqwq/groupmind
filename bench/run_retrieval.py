"""Retrieval-only comparisons on a real group. No data leaves this machine."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from bench import chunking, evaluate, metrics, realdata, tokenize
from bench.retrievers.bm25 import BM25
from bench.schema import HoldoutViolation, Visibility
from bench.tasks.real_tasks import clean_messages, identity_scores, quote_cases

CHUNKERS = {
    "msg": lambda ms: chunking.single_message(ms),
    "win5": lambda ms: chunking.fixed_window(ms, 5, 3),
    "win10": lambda ms: chunking.fixed_window(ms, 10, 5),
    "win20": lambda ms: chunking.fixed_window(ms, 20, 10),
}


def answerability_auc(index: BM25, cases: list, sample: int = 1500) -> dict:
    """Q3 at retrieval level: does the top score separate 'gold is visible' from 'gold not yet said'?

    The same query runs twice, once just before the gold exists. Only cases whose gold was
    retrieved in the visible run count, so a low AUC means the score cannot justify silence.
    """
    pos, neg = [], []
    for case in cases[:sample]:
        rank, top, _, _ = evaluate.rank_of(index, case, 20)
        if rank is None:
            continue
        gold_ts = min(b.end_ts for b in index.blocks if case.gold_msg_ids & set(b.msg_ids))
        hits = index.search(case.query, gold_ts, 1, case.channel)
        pos.append(top)
        neg.append(hits[0][1] if hits else 0.0)
    return {"n": len(pos), "auc": round(metrics.auc(pos, neg), 4)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--holdout", action="store_true")
    args = ap.parse_args()

    visibility = realdata.splits()[args.group]
    if visibility is not Visibility.DEV and not args.holdout:
        raise HoldoutViolation(f"{args.group} is {visibility.value}")

    raw = realdata.load_group(args.group)
    messages = clean_messages(raw)
    report: dict = {"group": args.group, "visibility": visibility.value, "messages": len(messages)}
    report["indexable"] = sum(bool(m.content) for m in messages)
    report["q5_identity"] = identity_scores(raw)

    query_sets = {}
    for label, context in (("reply", 0), ("recent3", 3)):
        cases, funnel = quote_cases(messages, context=context, visibility=visibility)
        query_sets[label] = cases
        report[f"q1_funnel_{label}"] = dict(funnel)

    runs, q3 = {}, {}
    for tok_name in ("jieba", "bigram", "unigram"):
        tok = tokenize.get(tok_name)
        for chunk_name, chunker in CHUNKERS.items():
            start = time.time()
            index = BM25(chunker(messages), tok)
            for query_label, cases in query_sets.items():
                key = f"{tok_name}+{chunk_name}+{query_label}"
                run = evaluate.evaluate(index, cases, allow_holdout=args.holdout)
                runs[key] = run
                print(key, run["summary"]["all"], f"{time.time() - start:.0f}s", flush=True)
            q3[f"{tok_name}+{chunk_name}"] = answerability_auc(index, query_sets["reply"])

    base = "jieba+win10+reply"
    report["q1"] = {k: r["summary"] for k, r in runs.items()}
    report["q1_vs_reference"] = {k: evaluate.compare(runs[base], r) for k, r in runs.items() if k != base}
    report["q3_auc"] = q3
    args.out.mkdir(parents=True, exist_ok=True)
    from bench import rawlog

    for key, run in runs.items():
        rawlog.write(rawlog.arm_file(args.out, "q1", key),
                     ({"arm": key, "case_id": cid, **row} for cid, row in run["per_case"].items()))
    (args.out / "retrieval.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
