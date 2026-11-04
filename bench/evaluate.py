"""Retrieval evaluation with enforced time visibility."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from bench import metrics
from bench.retrievers.bm25 import BM25
from bench.schema import RetrievalCase, require_dev

KS = (1, 5, 10, 20)
# Larger blocks reach gold in fewer ranks but cost more context, so also compare at a fixed message budget.
BUDGETS = (20, 50, 100)


class TimeLeak(RuntimeError):
    pass


def rank_of(index: BM25, case: RetrievalCase, k: int) -> tuple[int | None, float, int, int | None]:
    """Return (rank of first gold block, top score, messages returned, messages read up to gold)."""
    hits = index.search(case.query, case.as_of, k, case.channel)
    for block, _ in hits:
        if block.end_ts >= case.as_of:
            raise TimeLeak(f"{case.case_id}: {block.block_id} ends after as_of")
    rank, read, to_gold = None, 0, None
    for i, (block, _) in enumerate(hits, 1):
        read += len(block.msg_ids)
        if rank is None and case.gold_msg_ids & set(block.msg_ids):
            rank, to_gold = i, read
    return rank, (hits[0][1] if hits else 0.0), read, to_gold


def evaluate(index: BM25, cases: Iterable[RetrievalCase], allow_holdout: bool = False, depth: int = 20) -> dict:
    per_case: dict[str, dict] = {}
    for case in cases:
        require_dev(case.visibility, allow_holdout)
        rank, top, n_msgs, to_gold = rank_of(index, case, depth)
        per_case[case.case_id] = {
            "rank": rank, "top_score": top, "msgs": n_msgs, "msgs_to_gold": to_gold, "buckets": case.buckets,
        }
    return {"summary": summarize(per_case), "per_case": per_case}


def summarize(per_case: dict[str, dict]) -> dict:
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in per_case.values():
        groups["all"].append(row)
        for name, value in row["buckets"].items():
            groups[f"{name}={value}"].append(row)
    out = {}
    for name, rows in sorted(groups.items()):
        ranks = [r["rank"] for r in rows]
        out[name] = {
            "n": len(rows),
            **{f"R@{k}": round(metrics.recall_at(ranks, k), 4) for k in KS},
            **{f"R@msgs{b}": round(metrics.recall_at([r["msgs_to_gold"] for r in rows], b), 4) for b in BUDGETS},
            "MRR": round(metrics.mrr(ranks), 4),
            "msgs@20": round(sum(r["msgs"] for r in rows) / len(rows), 1),
        }
    return out


def compare(base: dict, other: dict, k: int = 10) -> dict:
    """Paired delta of R@k between two runs over their shared cases."""
    ids = sorted(set(base["per_case"]) & set(other["per_case"]))
    hit = lambda run, i: float((r := run["per_case"][i]["rank"]) is not None and r <= k)  # noqa: E731
    return metrics.paired_delta([hit(base, i) for i in ids], [hit(other, i) for i in ids])
