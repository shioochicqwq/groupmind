"""Regression check for bench.retrievers.frozen_pipeline (no model is called; cached vectors only).

1. overlap "none" must reproduce, block for block, the packed blocks of earlier answer-level runs:
   V2 (raw/embed_qa) and V0 (raw/depth K5, the version before 2026-11-05), every question and
   time point they recorded.
2. "none" and "index+route" must reproduce schemes A and B of the offline layer test
   (color_layers.json): evidence injected, block count and characters, question by question.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from bench import coloring, realdata
from bench.frozen import FROZEN, LEGACY, embedder
from bench.retrievers import frozen_pipeline as fp
from bench.run_abcd import prepare
from bench.schema import Visibility
from bench.tasks.real_tasks import clean_messages


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--manifest", action="store_true", help="also write the B block manifest next to the run")
    args = ap.parse_args()
    if realdata.splits()[args.group] is not Visibility.DEV:
        raise SystemExit("DEV only")
    ns = argparse.Namespace(group=args.group, out=args.out, labels=None, extra_segments=220, absent=150,
                            workers=8, budget=FROZEN["budget_chars"], colors_file=FROZEN["colors"])
    ctx = prepare(ns)
    colors = [json.loads(x) for x in (args.out / FROZEN["colors"]).read_text(encoding="utf-8").splitlines()]
    batches = coloring.batches(clean_messages(realdata.load_group(args.group)), 150, 20)

    def offline(*_a, **_k):
        raise RuntimeError("embedding cache miss: the check must not call the API")

    def retriever(config, mode):
        emb = embedder(config, args.out)
        emb._request = offline
        return fp.build(ctx, {**config, "overlap_dedup": mode}, emb, colors, batches)[0]

    report, ok = {"group": args.group}, True
    for name, config, file in (("V2", FROZEN, "raw/embed_qa/K5V2_rrf4_at1500.jsonl"),
                               ("V0", LEGACY, "raw/depth/K5_rrf4_at1500.jsonl")):
        r = retriever(config, "none")
        rows = [json.loads(x) for x in (args.out / file).open(encoding="utf-8")]
        diff = [x["question_id"] for x in rows if [b.block_id for b in r.retrieve(x["question"], x["as_of"])] != x["retrieved"]]
        report[f"none_vs_{name}_records"] = {"n": len(rows), "different": len(diff), "examples": diff[:5]}
        ok &= not diff

    layers = json.loads((args.out / "color_layers.json").read_text(encoding="utf-8"))["rows"]
    questions = {q["id"]: q for q in ctx.questions}
    for mode, scheme in (("none", "A"), ("index+route", "B")):
        r = retriever(FROZEN, mode)
        diff = []
        for row in layers:
            q = questions[row["id"]]
            packed = r.retrieve(q["question"], ctx.end_ts)
            got = {"injected": any(set(q["gold"]) & set(b.msg_ids) for b in packed), "blocks": len(packed),
                   "chars": sum(len(t) for t in r.feed(packed))}
            if any(got[k] != row[scheme][k] for k in got):
                diff.append(row["id"])
        report[f"{mode}_vs_layers_{scheme}"] = {"n": len(layers), "different": len(diff), "examples": diff[:5],
                                                "injected": round(sum(row[scheme]["injected"] for row in layers) / len(layers), 4)}
        ok &= not diff
    report["ok"] = bool(ok)
    if args.manifest:
        rows = fp.block_manifest(args.group, FROZEN["colors"], colors, batches, ctx.messages, FROZEN["overlap_dedup"])
        fp.write_manifest(args.out / "blocks.B.jsonl", rows)
        report["manifest"] = {"blocks": len(rows), "indexed_fewer": sum(len(x["indexed_msg_ids"]) < len(x["msg_ids"]) for x in rows),
                              "not_indexed": sum(not x["indexed_msg_ids"] for x in rows)}
    print(json.dumps(report, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
