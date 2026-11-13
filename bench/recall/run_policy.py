"""Dry run of the recall policy over the frozen retrieval: what would be shown, at which grain.
No answer model is called; this only describes the policy. DEV only.

For every benchmark question (asked at the end of the data), the frozen four-route ranking is
passed through bench.recall.policy from one point of view: `--me` is the alias whose memory this
is (a member, for imitation), or empty for a bystander who never spoke. The impressions come from
bench.recall.run_impress (`--impressions` names the set: the model that formed them, plus `.nocaution` for that variant).

Reported: grains of the ranked blocks, grains of what fits the budget, size of the memory text
against the frozen packing, at which grain each question's gold evidence ends up, and the grain of
the ranked blocks by age (age is not an input of the policy; the table shows what is left of it).
None of this is a score: the policy is not judged by QA accuracy.

    python -m bench.recall.run_policy --group 4fe395 --out <runs>/real-dev --impressions gemini-3.8-flash-high [--me P003]
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from bench import coloring, realdata
from bench.frozen import FROZEN, embedder
from bench.recall import policy
from bench.retrievers import frozen_pipeline as fp
from bench.retrievers import packing
from bench.run_abcd import prepare
from bench.schema import Visibility
from bench.tasks.real_tasks import clean_messages

DEPTH = 12  # ranked blocks the policy looks at
AGES = ((86400, "一天内"), (7 * 86400, "一周内"), (30 * 86400, "一个月内"), (float("inf"), "更早"))  # for the report only


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--me", default="", help="alias whose memory this is; empty = a silent bystander")
    ap.add_argument("--impressions", required=True, help="model whose impressions to use (run_impress)")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    if realdata.splits()[args.group] is not Visibility.DEV:
        raise SystemExit("DEV only")
    ns = argparse.Namespace(group=args.group, out=args.out, labels=None, extra_segments=220, absent=150,
                            workers=args.workers, budget=FROZEN["budget_chars"], colors_file=FROZEN["colors"])
    ctx = prepare(ns)
    colors = [json.loads(x) for x in (args.out / FROZEN["colors"]).open(encoding="utf-8")]
    batches = coloring.batches(clean_messages(realdata.load_group(args.group)), 150, 20)
    retriever, _ = fp.build(ctx, FROZEN, embedder(FROZEN, args.out), colors, batches, role="回忆策略|检索")
    rows = [json.loads(x) for x in (args.out / f"recall.impressions.{args.impressions}.jsonl").open(encoding="utf-8")]
    known = policy.index(rows)
    summary_of = {c["color_id"]: c.get("summary", "") for c in colors}
    back = policy.revisits(ctx.messages)
    if args.me and not any(m.author == args.me for m in ctx.messages):
        raise SystemExit(f"{args.me} never speaks in this group")

    ranked, shown, gold, roles, by_age, strengths = Counter(), Counter(), Counter(), Counter(), Counter(), Counter()
    chars_policy = chars_frozen = n = 0
    for q in ctx.questions:
        order = packing.global_rrf(retriever.routes(q["question"], ctx.end_ts))
        ev = policy.decide(order[:DEPTH], ctx.by_id, known, back, me=args.me, as_of=ctx.end_ts, query=q["question"])
        text, used = policy.render(ev, ctx.by_id, summary_of, ctx.end_ts, FROZEN["budget_chars"], me=args.me)
        frozen = packing.pack_in_order(order, retriever.feed, FROZEN["budget_chars"])
        n += 1
        chars_policy += len(text) - len(policy.GUIDE) - 2
        chars_frozen += sum(len(t) for t in retriever.feed(frozen))
        ranked.update(e.tier for e in ev)
        roles.update(e.role for e in ev)
        shown.update(e.tier for e in used)
        strengths.update(e.strength or "无" for e in ev)
        by_age.update((next(name for limit, name in AGES if ctx.end_ts - e.block.end_ts < limit), e.strength or "无") for e in ev)
        if q["gold"]:
            want = set(q["gold"])
            hit = [e for e in used if want & set(e.block.msg_ids)]
            in_frozen = any(want & set(b.msg_ids) for b in frozen)
            best = min((policy.TIERS.index(e.tier) for e in hit), default=3)
            gold[("冻结版给了原文" if in_frozen else "冻结版没给", policy.TIERS[best])] += 1
    summary = {"group": args.group, "me": args.me or "（旁观者）", "questions": n, "depth": DEPTH,
               "impressions_from": args.impressions, "roles_of_ranked_blocks": dict(roles),
               "impression_of_ranked_blocks": dict(strengths), "grain_of_ranked_blocks": dict(ranked), "grain_of_shown": dict(shown),
               "impression_of_ranked_blocks_by_age": {name: {s: by_age[(name, s)] for s in ("深", "中", "浅", "无")} for _, name in AGES},
               "mean_chars": {"policy": round(chars_policy / n), "frozen": round(chars_frozen / n)},
               "gold_evidence": {f"{a}→{b}": c for (a, b), c in sorted(gold.items())}}
    name = f"recall.policy2.{args.impressions}.{args.me or 'bystander'}.summary.json"
    (args.out / name).write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
