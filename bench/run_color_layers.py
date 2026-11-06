"""Three-scheme offline test of overlap duplicates and structure (retrieval layer only). DEV only.

Fixed: V2 embeddings, four routes, top 5 per route, global RRF k=60, strict packing into 1500
injected characters, raw blocks. No answer model is called.

A  original batch colours as they are.
B  duplicates removed without merging. Colour boundaries and the injected units stay the
   original blocks. Two steps, also reported apart:
   B-index  each overlap message is indexed in one block only (the earlier batch's matching
            colour); the later colour is indexed without it, but still injects its own messages.
   B-route  in each route list, a block whose messages all appear in higher-ranked blocks of
            that list is skipped and the next one moves up, so no message is ever lost.
C  B plus a global topic layer: colours that adjacent batches made of the same context form one
   topic (the merged-v1 groups). Topics are searched with the same four routes; a local block
   gains the topic's RRF score, and the best local block of each top topic joins the candidates.
   Only local blocks are injected.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from bench import chunking, ledger, metrics, realdata
from bench.color_fix import dedup_overlaps, merge_overlaps
from bench.embed import VectorIndex
from bench.frozen import FROZEN, embedder
from bench.memory_text import raw_blocks
from bench.retrievers import packing
from bench.retrievers.frozen_pipeline import skip_covered  # noqa: F401  (kept importable from here)
from bench.retrievers.bm25 import BM25
from bench.run_abcd import prepare
from bench.run_embed_ablation import raw_text
from bench.schema import Visibility
from bench import coloring
from bench.tasks.real_tasks import clean_messages

K, DEPTH, BUDGET, RRF_K = FROZEN["top_k"], 30, FROZEN["budget_chars"], FROZEN["rrf_k"]


def vec_raw_blocks(blocks, by_id, summary_of):
    return [x.__class__(x.block_id, x.msg_ids, x.end_ts, x.channel, raw_text(x, by_id, summary_of, "alias"), x.labels) for x in blocks]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--labels", type=Path)
    args = ap.parse_args()
    if realdata.splits()[args.group] is not Visibility.DEV:
        raise SystemExit("DEV only")
    ns = argparse.Namespace(group=args.group, out=args.out, labels=args.labels, extra_segments=220, absent=150,
                            workers=8, budget=BUDGET, colors_file=FROZEN["colors"])
    ctx = prepare(ns)
    by_id, channel, msgs = ctx.by_id, ctx.channel, ctx.messages
    feed = lambda bs: raw_blocks(bs, by_id)  # noqa: E731
    emb = embedder(FROZEN, args.out)
    colors = [json.loads(x) for x in (args.out / FROZEN["colors"]).read_text(encoding="utf-8").splitlines()]
    batches = coloring.batches(clean_messages(realdata.load_group(args.group)), 150, 20)

    # A: original local blocks.
    local_sum, local_raw = ctx.summary_blocks, ctx.raw_color_blocks
    by_color = ctx.by_color
    idx_a = [ctx.summary_index, ctx.raw_index,
             VectorIndex(local_sum, emb, "层次|A|摘要"), VectorIndex(vec_raw_blocks(local_raw, by_id, ctx.summary_of), emb, "层次|A|原文块")]

    # B-index: index texts without the overlap duplicates; injected units stay the original blocks.
    dedup, dedup_stats = dedup_overlaps(colors, batches)
    d_sum = [b for b in chunking.from_colors(msgs, dedup, "summary")]
    d_raw = [b for b in chunking.from_colors(msgs, dedup, "raw")]
    idx_b = [BM25(d_sum, ctx.tok), BM25(d_raw, ctx.tok),
             VectorIndex(d_sum, emb, "层次|B|摘要"), VectorIndex(vec_raw_blocks(d_raw, by_id, ctx.summary_of), emb, "层次|B|原文块")]

    # C: topics from the merged groups.
    merged, merge_stats = merge_overlaps(colors, batches)
    topic_of = {}
    for t, c in enumerate(merged):
        for old in c.get("merged_from", [c["color_id"]]):
            topic_of[old] = c["color_id"]
    t_sum = chunking.from_colors(msgs, merged, "summary")
    t_raw = chunking.from_colors(msgs, merged, "raw")
    members = defaultdict(list)
    for old, t in topic_of.items():
        if old in by_color:
            members[t].append(old)
    t_summary_of = {b.block_id: b.index_text for b in t_sum}
    idx_t = [BM25(t_sum, ctx.tok), BM25(t_raw, ctx.tok),
             VectorIndex(t_sum, emb, "层次|C|话题摘要"), VectorIndex(vec_raw_blocks(t_raw, by_id, t_summary_of), emb, "层次|C|话题原文")]

    def routes(indexes, q):
        # Results map back to the original local blocks by colour id.
        return [[by_color[b.block_id] for b, _ in idx.search(q, ctx.end_ts, DEPTH, channel) if b.block_id in by_color]
                for idx in indexes]

    rows = []
    for q in ctx.questions:
        gold = set(q["gold"])
        has = lambda b: bool(gold & set(b.msg_ids))  # noqa: E731
        ra = routes(idx_a, q["question"])
        rb_index = routes(idx_b, q["question"])
        variants = {
            "A": [r[:K] for r in ra],
            "B-index": [r[:K] for r in rb_index],
            "B-route": [skip_covered(r, K) for r in ra],
            "B": [skip_covered(r, K) for r in rb_index],
        }
        # C: topic ranks per route, then local candidates scored with local + topic RRF.
        tr = [[b.block_id for b, _ in idx.search(q["question"], ctx.end_ts, DEPTH, channel)] for idx in idx_t]
        topic_score = defaultdict(float)
        for r in tr:
            for rank, t in enumerate(r[:K], 1):
                topic_score[t] += 1.0 / (RRF_K + rank)
        local = variants["B"]
        local_score = packing.rrf_scores(local)
        cand = {b.block_id: b for r in local for b in r}
        local_rank = {}
        for r in rb_index:
            for rank, b in enumerate(r, 1):
                local_rank[b.block_id] = min(local_rank.get(b.block_id, 99), rank)
        for t in topic_score:
            ms = [m for m in members.get(t, []) if m in by_color]
            if ms:
                best = min(ms, key=lambda m: (local_rank.get(m, 99), m))
                cand.setdefault(best, by_color[best])
        scored = sorted(cand.values(), key=lambda b: (-(local_score.get(b.block_id, 0.0) + topic_score.get(topic_of.get(b.block_id, b.block_id), 0.0)), b.block_id))
        packed = {name: packing.pack_in_order(packing.global_rrf(v), feed, BUDGET) for name, v in variants.items()}
        packed["C"] = packing.pack_in_order(scored, feed, BUDGET)
        row = {"id": q["id"], "overlap": None}
        for name in ("A", "B-index", "B-route", "B"):
            v = variants[name]
            row[name] = {"route_hit@5": [any(has(b) for b in r) for r in v], "pool": any(has(b) for r in v for b in r),
                         "injected": any(has(b) for b in packed[name]), "blocks": len(packed[name]),
                         "chars": sum(len(x) for x in feed(packed[name]))}
        t_blocks = {b.block_id: b for b in t_sum}
        row["C"] = {"topic_hit@5": [any(has(t_blocks[t]) for t in r[:K] if t in t_blocks) for r in tr],
                    "pool": any(has(b) for b in cand.values()), "injected": any(has(b) for b in packed["C"]),
                    "blocks": len(packed["C"]), "chars": sum(len(x) for x in feed(packed["C"]))}
        rows.append(row)

    n = len(rows)
    names = ["BM25摘要", "BM25原文", "向量摘要", "向量原文"]
    summary = {"group": args.group, "n": n, "frozen": {k: FROZEN[k] for k in ("name", "colors", "top_k", "budget_chars")},
               "dedup_stats": dedup_stats, "merge_stats": merge_stats, "schemes": {}}
    for name in ("A", "B-index", "B-route", "B", "C"):
        s = {"injected": round(sum(r[name]["injected"] for r in rows) / n, 4), "pool": round(sum(r[name]["pool"] for r in rows) / n, 4),
             "avg_blocks": round(sum(r[name]["blocks"] for r in rows) / n, 2), "avg_chars": round(sum(r[name]["chars"] for r in rows) / n)}
        key = "topic_hit@5" if name == "C" else "route_hit@5"
        s["R@5"] = {nm: round(sum(r[name][key][j] for r in rows) / n, 4) for j, nm in enumerate(names)}
        if name != "A":
            s["vs_A_injected"] = metrics.paired_delta([float(r["A"]["injected"]) for r in rows], [float(r[name]["injected"]) for r in rows])
        if name == "C":
            s["vs_B_injected"] = metrics.paired_delta([float(r["B"]["injected"]) for r in rows], [float(r["C"]["injected"]) for r in rows])
        summary["schemes"][name] = s
    (args.out / "color_layers.json").write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False), encoding="utf-8")
    split = {"4fe395": "DEV-1", "ed14b7": "DEV-2"}.get(args.group, args.group)
    desc = {"A": "原始批次色块", "B-index": "去重（仅索引：重叠消息只计入一个色块），注入单元不变",
            "B-route": "去重（仅候选：完全被更前的块覆盖的块跳过），注入单元不变", "B": "去重不合并：B-index + B-route",
            "C": "分层：B + 全局话题（跨批合并组）RRF，注入局部片段"}
    ledger.append(args.out.parent / "ledger.jsonl", [ledger.row(
        f"C 重叠去重与分层（检索层，{split}）", name,
        ledger.cond(index="四路 RRF，每路前 5（冻结版 V2）", chunking=f"颜色块：{desc[name]}" + ("" if name == "A" else "（与此前实验条件不同）"),
                    tokenizer="jieba+习得词 + qwen3.7-text-embedding-flash（V2）", top_k=K, filter="否", feed="原文块（去重）",
                    budget_chars=BUDGET, model_main="-", judge="-", seed=0),
        {"n": n, **{k: v for k, v in s.items()}}, dataset="QQ", split=split, note=desc[name], raw=f"{args.out.name}/color_layers.json")
        for name, s in summary["schemes"].items()])
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
