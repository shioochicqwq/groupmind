"""Rank metrics and paired bootstrap; a missing rank means the gold was not retrieved."""
from __future__ import annotations

import random
from collections.abc import Iterable, Sequence


def recall_at(ranks: Iterable[int | None], k: int) -> float:
    ranks = list(ranks)
    return sum(1 for r in ranks if r is not None and r <= k) / len(ranks) if ranks else 0.0


def mrr(ranks: Iterable[int | None]) -> float:
    ranks = list(ranks)
    return sum(1 / r for r in ranks if r is not None) / len(ranks) if ranks else 0.0


def bootstrap_ci(values: Sequence[float], n: int = 2000, seed: int = 0) -> tuple[float, float]:
    if not values:
        return (0.0, 0.0)
    rng = random.Random(seed)
    means = sorted(sum(rng.choices(values, k=len(values))) / len(values) for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n) - 1]


def paired_delta(a: Sequence[float], b: Sequence[float], seed: int = 0) -> dict:
    """Mean of b - a over the same cases, with 95% CI and win/loss counts."""
    if len(a) != len(b):
        raise ValueError("paired comparison needs the same cases")
    diffs = [y - x for x, y in zip(a, b)]
    lo, hi = bootstrap_ci(diffs, seed=seed)
    return {
        "delta": sum(diffs) / len(diffs) if diffs else 0.0,
        "ci95": [lo, hi],
        "wins": sum(d > 0 for d in diffs),
        "losses": sum(d < 0 for d in diffs),
        "n": len(diffs),
    }


def auc(pos: Sequence[float], neg: Sequence[float]) -> float:
    """Mann-Whitney AUC; ties count half."""
    if not pos or not neg:
        return float("nan")
    ordered = sorted([(s, 1) for s in pos] + [(s, 0) for s in neg])
    rank_sum, i = 0.0, 0
    while i < len(ordered):
        j = i
        while j < len(ordered) and ordered[j][0] == ordered[i][0]:
            j += 1
        avg_rank = (i + 1 + j) / 2
        rank_sum += avg_rank * sum(flag for _, flag in ordered[i:j])
        i = j
    return (rank_sum - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))
