"""Does a better embedding turn into accuracy? Answer-level test of V2 and M1. DEV only.

The frozen version (four routes, top 5 per route, global RRF, strict packing into 1500
characters, raw blocks, no filter) stays as it is; only the two vector routes change:

  V2  qwen3.7-text-embedding-flash with text_type document/query and a retrieval instruction
  M1  the same settings on qwen3.7-text-embedding

Every vector comes from the ablation caches with the embedding API switched off. Answer
prompts are matched against the shared answer cache first; only changed injections call the
answer model. Scoring is three-state (bench.scoring).
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from bench import ledger, rawlog, realdata, scoring, usage
from bench.embed import AliyunEmbedder, VectorIndex
from bench.ledger import cond
from bench.llm import DEFAULT_MODEL, JUDGE_MODEL
from bench.memory_text import raw_blocks
from bench.retrievers import packing
from bench.run_abcd import ANSWER, Arm, build_inputs, evaluate_arm, prepare
from bench.run_embed_ablation import CONFIGS, INSTRUCT, raw_text
from bench.schema import Visibility

K, BUDGET, DEPTH = 5, 1500, 30
BASE = "K5:rrf4@1500"


def arm_name(config: str) -> str:
    return f"K5{config}:rrf4@{BUDGET}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--labels", type=Path)
    ap.add_argument("--extra-segments", type=int, default=220)
    ap.add_argument("--absent", type=int, default=150)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--configs", nargs="+", default=["V2", "M1"])
    ap.add_argument("--scan-only", action="store_true")
    args = ap.parse_args()
    args.budget = BUDGET
    if realdata.splits()[args.group] is not Visibility.DEV:
        raise SystemExit("this run sends data out and is DEV only")

    ctx = prepare(args)
    by_id, channel = ctx.by_id, ctx.channel
    feed = lambda bs: raw_blocks(bs, by_id)  # noqa: E731
    keyword = [ctx.summary_index, ctx.raw_index]

    def offline(*_a, **_k):
        raise RuntimeError("embedding cache miss: this run must not call the embedding API")

    arms = {}
    for name in args.configs:
        c = CONFIGS[name]
        cache = args.out / f"embed.ablation.{c['model']}.{c['dim']}.cache.jsonl"
        emb = AliyunEmbedder(cache, c["model"], c["dim"], c["asymmetric"], c["instruct"])
        emb._request = offline
        vs = VectorIndex(ctx.summary_blocks, emb, f"向量|{name}|摘要")
        vr = VectorIndex([x.__class__(x.block_id, x.msg_ids, x.end_ts, x.channel, raw_text(x, by_id, ctx.summary_of, c["raw"]), x.labels)
                          for x in ctx.raw_color_blocks], emb, f"向量|{name}|原文块")
        indexes = keyword + [vs, vr]

        def retrieve(q, t, indexes=indexes):
            routes = [[ctx.by_color[x.block_id] for x, _ in idx.search(q, t, K, channel)] for idx in indexes]
            return packing.pack_in_order(packing.global_rrf(routes), feed, BUDGET)

        arms[name] = Arm(arm_name(name), retrieve, None, feed, BUDGET)

    questions = ctx.questions
    absent_ids = {q["id"] for q in random.Random(0).sample(questions, min(args.absent, len(questions)))}
    conditions = [(q, ctx.end_ts, True) for q in questions] + [
        (q, q["first_ts"], False) for q in questions if q["id"] in absent_ids]

    # Baseline: the frozen version's records from the depth run.
    base_file = args.out / "raw" / "depth" / "K5_rrf4_at1500.jsonl"
    base = {(r["question_id"], r["visible"]): r for r in map(json.loads, base_file.open(encoding="utf-8"))}
    main_llm = ctx.main_llm
    scan, inputs = {}, {}
    for name, arm in arms.items():
        inputs[name] = build_inputs(arm, conditions, None)
        keys = [main_llm._key(ANSWER, p) for p in inputs[name][4]]
        changed = [base[(q["id"], v)]["answer"]["key"] != k for (q, _, v), k in zip(conditions, keys)]
        gold_in = [bool(set(q["gold"]) & {i for b in blocks for i in b.msg_ids})
                   for (q, _, v), blocks in zip(conditions, inputs[name][1])]
        vis = [i for i, c in enumerate(conditions) if c[2]]
        scan[arm.name] = {
            "inputs": len(keys), "changed_vs_frozen": sum(changed), "cached": sum(k in main_llm.cache for k in keys),
            "new_needed": len({k for k in keys if k not in main_llm.cache}),
            "gold_injected": round(sum(gold_in[i] for i in vis) / len(vis), 4),
            "frozen_gold_injected": round(sum(base[(conditions[i][0]["id"], True)]["gold_injected"] for i in vis) / len(vis), 4),
        }
        print(arm.name, scan[arm.name], flush=True)
    report = {"group": args.group, "scan": scan, "arms": {}, "instruct": INSTRUCT}
    (args.out / "embed_qa.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.scan_only:
        return 0

    usage.reset()
    llms = (ctx.fast_llm, main_llm, ctx.judge_llm)
    frozen_rows = json.loads((args.out / "depth.json").read_text(encoding="utf-8"))["arms"][BASE]["rows"]
    for name, arm in arms.items():
        c = CONFIGS[name]
        result = evaluate_arm(arm, conditions, llms, ctx.awkward, rawlog.arm_file(args.out, "embed_qa", arm.name))
        result["conditions"] = cond(
            index=f"四路（关键词两路 + 向量两路），每路前 {K}，全局 RRF，严格按名次打包；向量 {name}", chunking="颜色块",
            tokenizer=f"jieba+习得词 + {c['model']}（{c['dim']} 维，text_type 区分查询/文档，查询带指令）",
            top_k=K, filter="否", feed="原文块（去重）", budget_chars=BUDGET, model_main=DEFAULT_MODEL, judge=JUDGE_MODEL, seed=0)
        result.update(scoring.three_state(result["rows"]))
        result["vs_frozen"] = scoring.paired(frozen_rows, result["rows"])
        report["arms"][arm.name] = result
        print(arm.name, {k: v for k, v in result.items() if k not in ("rows", "conditions")}, flush=True)
        (args.out / "embed_qa.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    if len(arms) == 2:
        a, b = (report["arms"][arm_name(n)]["rows"] for n in args.configs)
        report["M1_vs_V2"] = scoring.paired(a, b)
    report["cost"] = usage.summary()
    (args.out / "embed_qa.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    usage.write(args.out / "usage.embed_qa.json", "I5 向量配置（问答层）")
    from bench.ledger_backfill import abcd

    ledger.append(args.out.parent / "ledger.jsonl", abcd(args.out.parent, args.out.name, "embed_qa"))
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
