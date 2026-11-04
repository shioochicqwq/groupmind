"""Candidate depth per route for E1 (four routes, global RRF, strict packing, 1500 chars). DEV only.

Only the depth K changes. Route lists are computed once at the deepest K and cut, with the
embedding API switched off, so nothing is retrieved twice. Answer prompts are built offline and
looked up in the shared answer cache, keyed by SHA-256 of model, system prompt and full
prompt. Only misses are sent to the model; a changed injection, even with the same evidence,
counts as a miss.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path

from bench import metrics, rawlog, realdata, usage
from bench.embed import AliyunEmbedder, VectorIndex
from bench.memory_text import raw_blocks
from bench.retrievers import packing
from bench.run_abcd import ANSWER, JUDGE, Arm, build_inputs, evaluate_arm, prepare
from bench.run_vector import EMBED_CHARS
from bench.schema import Visibility

DEPTHS = (3, 5, 10, 20, 30)
BASE = 10
ROUTES = ("关键词摘要", "关键词原文", "向量摘要", "向量原文")


def arm_name(k: int, budget: int) -> str:
    return f"K{k}:rrf4@{budget}"


def history(out: Path) -> dict[str, str]:
    """Answer-prompt hash -> the first earlier experiment/arm that sent that exact prompt."""
    seen: dict[str, str] = {}
    for path in sorted((out / "raw").glob("*/*.jsonl")):
        if path.parent.name == "depth":
            continue
        for line in path.open(encoding="utf-8"):
            r = json.loads(line)
            a = r.get("answer")
            if isinstance(a, dict) and a.get("key"):
                seen.setdefault(a["key"], f"{path.parent.name}/{path.stem}")
    return seen


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--labels", type=Path)
    ap.add_argument("--extra-segments", type=int, default=220)
    ap.add_argument("--absent", type=int, default=150)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--budget", type=int, default=1500)
    ap.add_argument("--scan-only", action="store_true", help="report cache hits and stop before any model call")
    args = ap.parse_args()
    if realdata.splits()[args.group] is not Visibility.DEV:
        raise SystemExit("this run sends data out and is DEV only")

    ctx = prepare(args)
    by_id, channel, b = ctx.by_id, ctx.channel, args.budget
    embedder = AliyunEmbedder(args.out / "embed.aliyun.cache.jsonl")

    def offline(*_a, **_k):
        raise RuntimeError("embedding cache miss: this experiment must not call the embedding API")

    embedder._request = offline
    vec_summary = VectorIndex(ctx.summary_blocks, embedder, "向量|摘要")
    vec_raw = VectorIndex(
        [x.__class__(x.block_id, x.msg_ids, x.end_ts, x.channel, ("\n".join(raw_blocks([x], by_id)) or " ")[:EMBED_CHARS],
                     x.labels) for x in ctx.raw_color_blocks],
        embedder, "向量|原文块",
    )
    indexes = [ctx.summary_index, ctx.raw_index, vec_summary, vec_raw]
    feed = lambda bs: raw_blocks(bs, by_id)  # noqa: E731
    deep: dict[tuple[str, float], list[list]] = {}

    def routes(q, t):
        if (q, t) not in deep:
            deep[(q, t)] = [[ctx.by_color[x.block_id] for x, _ in index.search(q, t, max(DEPTHS), channel)]
                            for index in indexes]
        return deep[(q, t)]

    def retriever(k):
        return lambda q, t: packing.pack_in_order(packing.global_rrf([r[:k] for r in routes(q, t)]), feed, b)

    arms = {k: Arm(arm_name(k, b), retriever(k), None, feed, b) for k in DEPTHS}
    questions = ctx.questions
    absent_ids = {q["id"] for q in random.Random(0).sample(questions, min(args.absent, len(questions)))}
    conditions = [(q, ctx.end_ts, True) for q in questions] + [
        (q, q["first_ts"], False) for q in questions if q["id"] in absent_ids]

    # 1-2. Offline injections, matched against every earlier answer prompt.
    past = history(args.out)
    main_llm, judge_llm = ctx.main_llm, ctx.judge_llm
    scan: dict = {}
    inputs: dict = {}
    for k, arm in arms.items():
        inputs[k] = build_inputs(arm, conditions, None)
        keys = [main_llm._key(ANSWER, p) for p in inputs[k][4]]
        sources: dict[str, int] = {}
        for key in keys:
            src = past.get(key) or ("仅在回答缓存" if key in main_llm.cache else "未命中")
            sources[src] = sources.get(src, 0) + 1
        scan[arm.name] = {
            "inputs": len(keys), "distinct": len(set(keys)),
            "cached": sum(key in main_llm.cache for key in keys),
            "new_needed": len({key for key in keys if key not in main_llm.cache}),
            "sources": dict(sorted(sources.items(), key=lambda kv: -kv[1])),
        }
        print(arm.name, scan[arm.name], flush=True)
    base_ref = args.out / "raw" / "packing" / f"E1_rrf4_at{b}.jsonl"
    if base_ref.exists():
        old = {(r["question_id"], r["visible"]): r["answer"]["key"] for r in map(json.loads, base_ref.open(encoding="utf-8"))}
        now = {(q["id"], v): main_llm._key(ANSWER, p) for (q, _, v), p in zip(conditions, inputs[BASE][4])}
        scan["K10 与 E1 原记录一致"] = f"{sum(old.get(x) == y for x, y in now.items())}/{len(now)}"
        print("K10 vs E1", scan["K10 与 E1 原记录一致"], flush=True)
    report: dict = {"group": args.group, "questions": len(questions), "absent_questions": len(absent_ids),
                    "depths": list(DEPTHS), "scan": scan, "arms": {},
                    "embedding": {"model": embedder.model, "dim": embedder.dim}}
    (args.out / "depth.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.scan_only:
        return 0

    # 3. Misses only: the caches answer everything else.
    usage.reset()
    llms = (ctx.fast_llm, main_llm, judge_llm)
    for k, arm in arms.items():
        report["arms"][arm.name] = evaluate_arm(arm, conditions, llms, ctx.awkward, rawlog.arm_file(args.out, "depth", arm.name))
        print(arm.name, {x: y for x, y in report["arms"][arm.name].items() if x not in ("rows", "conditions")}, flush=True)
        (args.out / "depth.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    # 4. Merge: statistics, cost and mechanisms.
    spent = usage.summary()
    report["cost"] = {arm.name: {role: spent[role] for role in spent if role.endswith("|" + arm.name)} for arm in arms.values()}
    report["paired"] = paired(report, arms, b)
    report["mechanism"] = mechanism(conditions, routes, arms, inputs, report, by_id)
    (args.out / "depth.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    usage.write(args.out / "usage.depth.json", "K 候选深度")
    from bench import ledger
    from bench.ledger_backfill import abcd

    ledger.append(args.out.parent / "ledger.jsonl", abcd(args.out.parent, args.out.name, "depth"))
    print("done")
    return 0


def paired(report, arms, b) -> dict:
    def correct(k):
        return {r["id"]: float(r["correct"]) for r in report["arms"][arm_name(k, b)]["rows"] if r["visible"]}

    ids = sorted(correct(BASE))
    out = {}
    pairs = [(k, BASE) for k in DEPTHS if k != BASE] + [(20, 5), (30, 20), (5, 3)]
    for new, old in pairs:
        x, y = correct(old), correct(new)
        d = metrics.paired_delta([x[i] for i in ids], [y[i] for i in ids])
        out[f"K{new} vs K{old}"] = {**d, "rescued": sum(y[i] > x[i] for i in ids), "lost": sum(y[i] < x[i] for i in ids)}
    return out


def mechanism(conditions, routes, arms, inputs, report, by_id) -> dict:
    """Why answers change with K: where the gold block sits in each route and in the packed list."""
    per_k = {}
    visible = [i for i, c in enumerate(conditions) if c[2]]
    for k, arm in arms.items():
        rows = {r["id"]: r for r in report["arms"][arm.name]["rows"] if r["visible"]}
        per_k[k] = []
        for i in visible:
            q, t, _ = conditions[i]
            gold = set(q["gold"])
            lists = routes(q["question"], t)
            has = lambda blk: bool(gold & set(blk.msg_ids))  # noqa: E731
            ranks = [next((n for n, blk in enumerate(r, 1) if has(blk)), None) for r in lists]
            chosen = inputs[k][1][i]
            pos = next((n for n, blk in enumerate(chosen, 1) if has(blk)), None)
            fused = packing.global_rrf([r[:k] for r in lists])
            per_k[k].append({
                "id": q["id"], "correct": rows[q["id"]]["correct"], "gold_in": pos is not None, "gold_pos": pos,
                "blocks": len(chosen), "chars": rows[q["id"]]["chars"],
                "candidate": any(r is not None and r <= k for r in ranks),
                "fused_rank": next((n for n, blk in enumerate(fused, 1) if has(blk)), None),
                "route_ranks": ranks,
                "distractor_chars_before": sum(len(x) for x in raw_blocks(chosen[: pos - 1], by_id)) if pos else None,
                "prompt_key": hashlib.sha256(inputs[k][4][i].encode()).hexdigest()[:16],
            })
    base = {r["id"]: r for r in per_k[BASE]}
    out = {"per_k": {}, "vs_K10": {}}
    for k, rows in per_k.items():
        n = len(rows)
        out["per_k"][f"K{k}"] = {
            "gold_candidate": round(sum(r["candidate"] for r in rows) / n, 4),
            "gold_injected": round(sum(r["gold_in"] for r in rows) / n, 4),
            "squeezed": round(sum(r["candidate"] and not r["gold_in"] for r in rows) / n, 4),
            "acc_when_injected": _rate([r["correct"] for r in rows if r["gold_in"]]),
            "acc_when_not": _rate([r["correct"] for r in rows if not r["gold_in"]]),
            "avg_blocks": round(sum(r["blocks"] for r in rows) / n, 2),
            "avg_gold_pos": round(_mean([r["gold_pos"] for r in rows if r["gold_pos"]]), 2),
            "avg_distractor_chars_before": round(_mean([r["distractor_chars_before"] for r in rows if r["gold_pos"]]), 1),
            "single_route_gold": round(sum(sum(x is not None and x <= k for x in r["route_ranks"]) == 1 for r in rows) / n, 4),
        }
        if k == BASE:
            continue
        cats: dict[str, dict[str, int]] = {}
        for r in rows:
            o = base[r["id"]]
            if r["gold_in"] and not o["gold_in"]:
                why = ("尾部候选让位，证据挤进来" if o["candidate"] else "更深候选带来新证据")
            elif o["gold_in"] and not r["gold_in"]:
                why = ("证据不在前 K（独有证据丢失）" if not r["candidate"] else "证据仍在候选，被挤出注入")
            elif r["gold_in"] and o["gold_in"]:
                why = "双方都有证据，内容或顺序不同" if r["prompt_key"] != o["prompt_key"] else "注入完全相同"
            else:
                why = "双方都无证据" + ("，注入完全相同" if r["prompt_key"] == o["prompt_key"] else "")
            flip = "救回" if r["correct"] and not o["correct"] else "退化" if o["correct"] and not r["correct"] else "不变"
            cats.setdefault(why, {"救回": 0, "退化": 0, "不变": 0})[flip] += 1
        same = [r for r in rows if r["gold_in"] and base[r["id"]]["gold_in"] and r["prompt_key"] != base[r["id"]]["prompt_key"]]
        out["vs_K10"][f"K{k}"] = {
            "categories": cats,
            "both_have_gold_changed": {
                "n": len(same),
                "gold_pos_delta": round(_mean([r["gold_pos"] - base[r["id"]]["gold_pos"] for r in same]), 2),
                "blocks_delta": round(_mean([r["blocks"] - base[r["id"]]["blocks"] for r in same]), 2),
                "distractor_before_delta": round(_mean([r["distractor_chars_before"] - base[r["id"]]["distractor_chars_before"]
                                                        for r in same]), 1),
            },
        }
    out["rows"] = {f"K{k}": rows for k, rows in per_k.items()}
    return out


def _mean(xs) -> float:
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


def _rate(xs) -> float | None:
    xs = list(xs)
    return round(sum(xs) / len(xs), 4) if xs else None


if __name__ == "__main__":
    raise SystemExit(main())
