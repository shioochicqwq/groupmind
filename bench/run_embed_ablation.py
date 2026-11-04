"""Embedding ablation on the retrieval layer only (no answer model). DEV only.

Keyword routes stay fixed. Each config changes how the two vector routes embed documents and
queries; results are per-route recall and the evidence-injection rate of the frozen version
(four routes, top 5 per route, global RRF, 1500 characters), re-packed offline.

Configs, cheapest first after V0:
  V0  current: no text_type, no instruction, raw text "alias: content", first 1000 chars
  V1  text_type=document for documents, query for queries
  V2  V1 + retrieval instruction on queries
  M1  V2 with qwen3.7-text-embedding (the larger sibling model)
  V3  V2, raw text without aliases
  V4  V2, raw text prefixed with the colour summary
  V5  V2 at 1024 dimensions
A token cap stops before any config that would push new embedding tokens past it.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from bench import ledger, metrics, realdata, usage
from bench.embed import AliyunEmbedder, VectorIndex
from bench.memory_text import raw_blocks
from bench.retrievers import packing
from bench.run_abcd import prepare
from bench.run_vector import EMBED_CHARS
from bench.schema import Visibility
from bench.tasks import silver

INSTRUCT = "给定群聊里的一个问题，检索能回答这个问题的聊天记录"
CONFIGS = {
    "V0": dict(model="qwen3.7-text-embedding-flash", dim=768, asymmetric=False, instruct="", raw="alias"),
    "V1": dict(model="qwen3.7-text-embedding-flash", dim=768, asymmetric=True, instruct="", raw="alias"),
    "V2": dict(model="qwen3.7-text-embedding-flash", dim=768, asymmetric=True, instruct=INSTRUCT, raw="alias"),
    "M1": dict(model="qwen3.7-text-embedding", dim=768, asymmetric=True, instruct=INSTRUCT, raw="alias"),
    "V3": dict(model="qwen3.7-text-embedding-flash", dim=768, asymmetric=True, instruct=INSTRUCT, raw="plain"),
    "V4": dict(model="qwen3.7-text-embedding-flash", dim=768, asymmetric=True, instruct=INSTRUCT, raw="summary+alias"),
    "V5": dict(model="qwen3.7-text-embedding-flash", dim=1024, asymmetric=True, instruct=INSTRUCT, raw="alias"),
}
DESCRIBE = {
    "V0": "现状：不区分查询和文档，无指令，原文带化名", "V1": "文档 document / 查询 query",
    "V2": "V1 + 查询加检索指令", "M1": "V2，换 qwen3.7-text-embedding", "V3": "V2，原文去掉化名",
    "V4": "V2，原文前加颜色摘要", "V5": "V2，1024 维",
}
DEPTH, K, BUDGET = 30, 5, 1500


def raw_text(block, by_id, summary_of, mode: str) -> str:
    if mode == "plain":
        text = "\n".join(by_id[i].content for i in block.msg_ids if by_id[i].content)
    else:
        text = "\n".join(raw_blocks([block], by_id))
    if mode == "summary+alias":
        text = f"{summary_of.get(block.block_id, '')}\n{text}"
    return (text or " ")[:EMBED_CHARS]


def run_group(args, group: str, out: Path, cap: int, spent: dict) -> dict:
    ns = argparse.Namespace(group=group, out=out, labels=args.labels if group == args.labels_group else None,
                            extra_segments=220, absent=150, workers=8, budget=BUDGET)
    ctx = prepare(ns)
    by_id, channel = ctx.by_id, ctx.channel
    questions = [q for q in ctx.questions]
    feed = lambda bs: raw_blocks(bs, by_id)  # noqa: E731
    keyword = [[[ctx.by_color[x.block_id] for x, _ in idx.search(q["question"], ctx.end_ts, DEPTH, channel)]
                for idx in (ctx.summary_index, ctx.raw_index)] for q in questions]
    has = lambda b, gold: bool(gold & set(b.msg_ids))  # noqa: E731
    result = {}
    for name in args.configs:
        c = CONFIGS[name]
        cache = out / ("embed.aliyun.cache.jsonl" if name == "V0" else f"embed.ablation.{c['model']}.{c['dim']}.cache.jsonl")
        emb = AliyunEmbedder(cache, c["model"], c["dim"], c["asymmetric"], c["instruct"])
        docs_s = [b.index_text for b in ctx.summary_blocks]
        docs_r = [raw_text(b, by_id, ctx.summary_of, c["raw"]) for b in ctx.raw_color_blocks]
        need = sum(len(t) for t, task in [(t, "RETRIEVAL_DOCUMENT") for t in docs_s + docs_r] + [(q["question"], "RETRIEVAL_QUERY") for q in questions]
                   if emb._key(t, task) not in emb.cache)
        # Chinese is roughly 0.75 tokens per character on this model.
        if spent["new_tokens"] + 0.75 * need > cap:
            result[name] = {"skipped": f"would exceed the {cap} token cap (needs about {int(0.75 * need)})"}
            print(group, name, result[name], flush=True)
            continue
        before = sum(emb.spent.values())
        vs = VectorIndex(ctx.summary_blocks, emb, f"向量消融|{name}|摘要")
        vr = VectorIndex([x.__class__(x.block_id, x.msg_ids, x.end_ts, x.channel, t, x.labels)
                          for x, t in zip(ctx.raw_color_blocks, docs_r)], emb, f"向量消融|{name}|原文块")
        rows = []
        for q, kw in zip(questions, keyword):
            gold = set(q["gold"])
            vec = [[ctx.by_color[x.block_id] for x, _ in idx.search(q["question"], ctx.end_ts, DEPTH, channel)] for idx in (vs, vr)]
            routes = kw + vec
            ranks = [next((n for n, b in enumerate(r, 1) if has(b, gold)), None) for r in routes]
            packed = packing.pack_in_order(packing.global_rrf([r[:K] for r in routes]), feed, BUDGET)
            rows.append({"id": q["id"], "ranks": ranks, "injected": any(has(b, gold) for b in packed),
                         "overlap": silver.char_overlap(q["question"], q["evidence_text"])})
        new = sum(emb.spent.values()) - before
        spent["new_tokens"] += new
        result[name] = {"rows": rows, "new_tokens": new, "config": c}
        print(group, name, "new tokens", new, "injected", round(sum(r["injected"] for r in rows) / len(rows), 4), flush=True)
    return result


def summarize(res: dict) -> dict:
    base = {r["id"]: r for r in res["V0"]["rows"]}
    out = {}
    for name, r in res.items():
        if "rows" not in r:
            out[name] = r
            continue
        rows = r["rows"]
        n = len(rows)
        s = {"n": n, "new_tokens": r["new_tokens"],
             "injected": round(sum(x["injected"] for x in rows) / n, 4),
             "pool": round(sum(any(k is not None and k <= K for k in x["ranks"]) for x in rows) / n, 4)}
        for j, route in enumerate(("BM25摘要", "BM25原文", "向量摘要", "向量原文")):
            s[route] = {f"R@{k}": round(sum(x["ranks"][j] is not None and x["ranks"][j] <= k for x in rows) / n, 4) for k in (1, 5, 10, 30)}
        low = [x for x in rows if x["overlap"] == "low"]
        s["low_overlap"] = {"n": len(low), "向量摘要R@5": round(sum(x["ranks"][2] is not None and x["ranks"][2] <= 5 for x in low) / len(low), 4),
                            "向量原文R@5": round(sum(x["ranks"][3] is not None and x["ranks"][3] <= 5 for x in low) / len(low), 4),
                            "injected": round(sum(x["injected"] for x in low) / len(low), 4)}
        vec_only = lambda x: any(k is not None and k <= K for k in x["ranks"][2:]) and not any(k is not None and k <= K for k in x["ranks"][:2])  # noqa: E731
        s["vector_only@5"] = sum(vec_only(x) for x in rows)
        ids = sorted(base)
        cur = {x["id"]: x for x in rows}
        for key, f in (("injected", lambda x: float(x["injected"])),
                       ("向量摘要R@5", lambda x: float(x["ranks"][2] is not None and x["ranks"][2] <= 5)),
                       ("向量原文R@5", lambda x: float(x["ranks"][3] is not None and x["ranks"][3] <= 5))):
            s[f"vs_V0:{key}"] = metrics.paired_delta([f(base[i]) for i in ids], [f(cur[i]) for i in ids])
        out[name] = s
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=Path, required=True)
    ap.add_argument("--labels", type=Path)
    ap.add_argument("--labels-group", default="4fe395")
    ap.add_argument("--configs", nargs="+", default=list(CONFIGS))
    ap.add_argument("--cap", type=int, default=4_000_000, help="new embedding tokens allowed across both groups")
    args = ap.parse_args()
    groups = {"4fe395": "real-dev", "ed14b7": "real-dev2"}
    spent = {"new_tokens": 0}
    report = {"configs": {k: {**CONFIGS[k], "describe": DESCRIBE[k]} for k in args.configs}, "instruct": INSTRUCT,
              "k": K, "budget": BUDGET, "groups": {}}
    rows_for_ledger = []
    for group, folder in groups.items():
        if realdata.splits()[group] is not Visibility.DEV:
            raise SystemExit("DEV only")
        res = run_group(args, group, args.runs / folder, args.cap, spent)
        summary = summarize(res)
        report["groups"][group] = summary
        (args.runs / folder / "embed_ablation.rows.json").write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
        split = {"4fe395": "DEV-1", "ed14b7": "DEV-2"}[group]
        for name, s in summary.items():
            if "n" not in s:
                continue
            c = CONFIGS[name]
            rows_for_ledger.append(ledger.row(
                f"I5 向量配置消融（检索层，{split}）", name,
                ledger.cond(index="四路：关键词两路 + 向量两路（检索层，不回答）", chunking="颜色块",
                            tokenizer=f"jieba+习得词 + {c['model']}（{c['dim']} 维）", top_k=K, filter="否",
                            feed="原文块（去重，离线重新打包）", budget_chars=BUDGET, model_main="-", judge="-", seed=0),
                {k: v for k, v in s.items() if not k.startswith("vs_")} | {"vs_V0_injected": s.get("vs_V0:injected")},
                dataset="QQ", split=split, note=DESCRIBE[name],
                tokens={"向量": {"calls": 0, "prompt": s["new_tokens"], "completion": 0, "new_prompt": s["new_tokens"]}},
                raw=f"{folder}/embed_ablation.rows.json"))
    report["new_tokens_total"] = spent["new_tokens"]
    (args.runs / "embed_ablation.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    ledger.append(args.runs / "ledger.jsonl", rows_for_ledger)
    usage.write(args.runs / "usage.embed_ablation.json", "I5 向量配置消融")
    print("done, new embedding tokens", spent["new_tokens"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
