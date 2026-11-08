"""Vector retrieval (I4, I5, I6): added to the two-way keyword fusion, at a fixed injected budget. DEV only.

Arms already run by run_abcd reuse its cache, so only the new arms cost model calls.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from bench import metrics, rawlog, realdata, usage
from bench.embed import AliyunEmbedder, Embedder, VectorIndex
from bench.memory_text import merged_windows, raw_blocks
from bench.retrievers.bm25 import BM25
from bench.retrievers.fusion import quota, rrf
from bench.run_abcd import Arm, evaluate_arm, prepare
from bench.schema import Visibility
from bench import chunking

DEPTH = 30
# Raw blocks are embedded from their first characters; longer text would exceed the free-tier pace.
EMBED_CHARS = 1000


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--labels", type=Path)
    ap.add_argument("--extra-segments", type=int, default=220)
    ap.add_argument("--absent", type=int, default=150)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--budget", type=int, default=1500)
    ap.add_argument("--embedder", choices=("aliyun", "gemini"), default="aliyun")
    ap.add_argument("--embed-model", default="qwen3.7-text-embedding-flash")
    ap.add_argument("--vectors", default="", help="V2 / M1 etc. from CONFIGS; empty keeps the old --embedder/--embed-model path")
    ap.add_argument("--experiment", default="vector", help="result file, raw folder and ledger section name; use vector_V2 for the V2 re-run")
    args = ap.parse_args()
    if realdata.splits()[args.group] is not Visibility.DEV:
        raise SystemExit("this run sends data out and is DEV only")
    if not (args.out / "q2b_questions.json").exists():
        raise SystemExit("run bench.run_abcd first; this experiment reuses its questions")

    ctx = prepare(args)
    channel, by_id = ctx.channel, ctx.by_id
    if args.vectors:
        from bench.run_embed_ablation import CONFIGS  # local: that module imports EMBED_CHARS from here

        vec_conf = CONFIGS[args.vectors]
        embedder = AliyunEmbedder(args.out / f"embed.ablation.{vec_conf['model']}.{vec_conf['dim']}.cache.jsonl",
                                  vec_conf["model"], vec_conf["dim"], vec_conf["asymmetric"], vec_conf["instruct"])
    else:
        embedder = (AliyunEmbedder(args.out / "embed.aliyun.cache.jsonl", args.embed_model) if args.embedder == "aliyun"
                    else Embedder(args.out / "embed.cache.jsonl"))
    vec_summary = VectorIndex(ctx.summary_blocks, embedder, "向量|摘要")
    vec_raw = VectorIndex(
        [b.__class__(b.block_id, b.msg_ids, b.end_ts, b.channel, ("\n".join(raw_blocks([b], by_id)) or " ")[:EMBED_CHARS], b.labels)
         for b in ctx.raw_color_blocks],
        embedder, "向量|原文块",
    )
    windows = BM25(chunking.fixed_window(ctx.messages, 10, 5), ctx.tok)

    def ranked(fn):
        return lambda q, t: [b for b, _ in fn(q, t)]

    raw_feed = lambda bs: raw_blocks(bs, by_id)  # noqa: E731
    keyword = [ctx.summary_index, ctx.raw_index]
    vectors = [vec_summary, vec_raw]
    b = args.budget
    arms = [
        Arm(f"A:raw->raw@{b}", ranked(lambda q, t: ctx.raw_index.search(q, t, DEPTH, channel)), None, raw_feed, b),
        Arm(f"D:fused->raw@{b}", ranked(lambda q, t: rrf(keyword, ctx.by_color, q, t, DEPTH, channel)), None, raw_feed, b),
        Arm(f"ref:win10@{b}", ranked(lambda q, t: windows.search(q, t, DEPTH, channel)), None,
            lambda bs: merged_windows(bs, by_id, ctx.order), b),
        Arm(f"V:summary->raw@{b}", ranked(lambda q, t: vec_summary.search(q, t, DEPTH, channel)), None, raw_feed, b),
        Arm(f"V:raw->raw@{b}", ranked(lambda q, t: vec_raw.search(q, t, DEPTH, channel)), None, raw_feed, b),
        Arm(f"DV:fused4->raw@{b}", ranked(lambda q, t: rrf(keyword + vectors, ctx.by_color, q, t, DEPTH, channel)),
            None, raw_feed, b),
        Arm(f"Dq:quota->raw@{b}", ranked(lambda q, t: quota(keyword, ctx.by_color, q, t, DEPTH, channel)), None, raw_feed, b),
        Arm(f"DVq:quota4->raw@{b}", ranked(lambda q, t: quota(keyword + vectors, ctx.by_color, q, t, DEPTH, channel, 2)),
            None, raw_feed, b),
    ]
    questions = ctx.questions
    absent_ids = {q["id"] for q in random.Random(0).sample(questions, min(args.absent, len(questions)))}
    conditions = [(q, ctx.end_ts, True) for q in questions] + [
        (q, q["first_ts"], False) for q in questions if q["id"] in absent_ids]

    report: dict = {"group": args.group, "questions": len(questions), "absent_questions": len(absent_ids), "arms": {},
                    "embedding": {"model": embedder.model, "dim": embedder.dim}}
    report_path = args.out / f"{args.experiment}.json"
    for arm in arms:
        report["arms"][arm.name] = evaluate_arm(arm, conditions, (ctx.fast_llm, ctx.main_llm, ctx.judge_llm), ctx.awkward,
                                                rawlog.arm_file(args.out, args.experiment, arm.name))
        print(arm.name, {k: v for k, v in report["arms"][arm.name].items() if k not in ("rows", "conditions")}, flush=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    def correct(name):
        return {r["id"]: float(r["correct"]) for r in report["arms"][name]["rows"] if r["visible"]}

    ids = sorted(correct(f"D:fused->raw@{b}"))
    base = f"D:fused->raw@{b}"
    report["paired"] = {
        f"{n} vs {ref}": metrics.paired_delta([correct(ref)[i] for i in ids], [correct(n)[i] for i in ids])
        for ref in (base, f"ref:win10@{b}") for n in report["arms"] if n != ref
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    usage.write(args.out / f"usage.{args.experiment}.json", "I4 向量检索")
    from bench import ledger
    from bench.ledger_backfill import abcd

    ledger.append(args.out.parent / "ledger.jsonl", abcd(args.out.parent, args.out.name, args.experiment))
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
