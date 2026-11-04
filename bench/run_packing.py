"""Packing several retrieval routes into a 1500-character injection (E1-E4). DEV only.

Four routes: keyword over summaries and over raw blocks, vector over both. The keyword-only
variants show whether the packer matters without vectors.
"""
from __future__ import annotations

import argparse
import json
import random
from functools import partial
from pathlib import Path

from bench import metrics, rawlog, realdata, usage
from bench.embed import AliyunEmbedder, VectorIndex
from bench.memory_text import raw_blocks
from bench.retrievers import packing
from bench.run_abcd import Arm, evaluate_arm, prepare
from bench.run_vector import EMBED_CHARS
from bench.schema import Visibility

ROUTE_DEPTH = 10


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--labels", type=Path)
    ap.add_argument("--extra-segments", type=int, default=220)
    ap.add_argument("--absent", type=int, default=150)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--budget", type=int, default=1500)
    args = ap.parse_args()
    if realdata.splits()[args.group] is not Visibility.DEV:
        raise SystemExit("this run sends data out and is DEV only")

    ctx = prepare(args)
    by_id, channel, b = ctx.by_id, ctx.channel, args.budget
    embedder = AliyunEmbedder(args.out / "embed.aliyun.cache.jsonl")
    vec_summary = VectorIndex(ctx.summary_blocks, embedder, "向量|摘要")
    vec_raw = VectorIndex(
        [x.__class__(x.block_id, x.msg_ids, x.end_ts, x.channel, ("\n".join(raw_blocks([x], by_id)) or " ")[:EMBED_CHARS],
                     x.labels) for x in ctx.raw_color_blocks],
        embedder, "向量|原文块",
    )
    # Vector blocks carry embedding text; answers must use the shared raw-block objects.
    keyword = [ctx.summary_index, ctx.raw_index]
    all_routes = keyword + [vec_summary, vec_raw]
    feed = lambda bs: raw_blocks(bs, by_id)  # noqa: E731

    def routes_for(indexes):
        def get(q, t):
            return [[ctx.by_color[x.block_id] for x, _ in index.search(q, t, ROUTE_DEPTH, channel)] for index in indexes]
        return get

    def packer(kind, indexes):
        get = routes_for(indexes)

        def retrieve(q, t):
            routes = get(q, t)
            if kind == "E1":
                return packing.pack_in_order(packing.global_rrf(routes), feed, b)
            if kind == "E2":
                return packing.pack_in_order(packing.round_robin(routes), feed, b)
            if kind == "E3":
                return packing.reserved(routes, feed, b)
            return packing.budget_aware(routes, feed, b)
        return retrieve

    names = {"E1": "rrf", "E2": "rr", "E3": "reserve", "E4": "aware"}
    arms = []
    for n_routes, indexes in ((4, all_routes), (2, keyword)):
        for kind in ("E1", "E2", "E3", "E4"):
            arms.append(Arm(f"{kind}:{names[kind]}{n_routes}@{b}", packer(kind, indexes), None, feed, b))

    questions = ctx.questions
    absent_ids = {q["id"] for q in random.Random(0).sample(questions, min(args.absent, len(questions)))}
    conditions = [(q, ctx.end_ts, True) for q in questions] + [
        (q, q["first_ts"], False) for q in questions if q["id"] in absent_ids]
    report: dict = {"group": args.group, "questions": len(questions), "absent_questions": len(absent_ids), "arms": {},
                    "route_depth": ROUTE_DEPTH, "embedding": {"model": embedder.model, "dim": embedder.dim}}
    llms = (ctx.fast_llm, ctx.main_llm, ctx.judge_llm)
    for arm in arms:
        report["arms"][arm.name] = evaluate_arm(arm, conditions, llms, ctx.awkward, rawlog.arm_file(args.out, "packing", arm.name))
        print(arm.name, {k: v for k, v in report["arms"][arm.name].items() if k not in ("rows", "conditions")}, flush=True)
        (args.out / "packing.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    def correct(name):
        return {r["id"]: float(r["correct"]) for r in report["arms"][name]["rows"] if r["visible"]}

    ids = sorted(correct(arms[0].name))
    pairs = {}
    for n_routes in (4, 2):
        base = f"E1:rrf{n_routes}@{b}"
        for kind in ("E2", "E3", "E4"):
            other = f"{kind}:{names[kind]}{n_routes}@{b}"
            pairs[f"{other} vs {base}"] = metrics.paired_delta([correct(base)[i] for i in ids], [correct(other)[i] for i in ids])
    for kind in ("E1", "E2", "E3", "E4"):
        four, two = f"{kind}:{names[kind]}4@{b}", f"{kind}:{names[kind]}2@{b}"
        pairs[f"{four} vs {two}"] = metrics.paired_delta([correct(two)[i] for i in ids], [correct(four)[i] for i in ids])
    report["paired"] = pairs
    (args.out / "packing.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    usage.write(args.out / "usage.packing.json", "E 打包与保底")
    from bench import ledger
    from bench.ledger_backfill import abcd

    ledger.append(args.out.parent / "ledger.jsonl", abcd(args.out.parent, args.out.name, "packing"))
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
