"""Three-state scoring (user decision, 2026-11-04).

Each answer is correct (1), wrong (0) or empty (NULL: the call came back empty, mostly a
safety block, so we cannot tell whether it would have been right). Two accuracies are
reported side by side, with the empty rate:

- end-to-end accuracy = correct / all questions (an empty answer is a failure; the historical score)
- effective accuracy  = correct / non-empty answers (accuracy when the system did produce output)

Effective accuracy can carry selection bias, so it is never used on its own to rank arms.
"""
from __future__ import annotations

from collections.abc import Iterable

from bench import metrics


def state(row: dict) -> int | None:
    """1 correct, 0 wrong, None empty, for a visible row."""
    if not (row.get("answer") or "").strip():
        return None
    return int(bool(row["correct"]))


def _rate(values: list[float]) -> tuple[float | None, list[float]]:
    if not values:
        return None, []
    return round(sum(values) / len(values), 4), [round(x, 3) for x in metrics.bootstrap_ci(values)]


def three_state(rows: Iterable[dict]) -> dict:
    rows = list(rows)
    pos = [r for r in rows if r["visible"]]
    neg = [r for r in rows if not r["visible"]]
    states = [state(r) for r in pos]
    answered = [s for s in states if s is not None]
    out: dict = {"scoring": "三态：端到端 + 有效回答", "n": len(pos), "n_empty": len(states) - len(answered),
                 "n_answered": len(answered)}
    out["accuracy"], out["accuracy_ci95"] = _rate([float(s or 0) for s in states])
    out["accuracy_effective"], out["accuracy_effective_ci95"] = _rate([float(s) for s in answered])
    out["empty_rate"] = round(out["n_empty"] / len(pos), 4) if pos else None
    if neg and "refused" in neg[0]:
        neg_answered = [r for r in neg if (r.get("answer") or "").strip()]
        out["refusal_when_absent"] = round(sum(r["refused"] for r in neg) / len(neg), 4)
        out["refusal_effective"] = round(sum(r["refused"] for r in neg_answered) / len(neg_answered), 4) if neg_answered else None
        out["empty_rate_absent"] = round(1 - len(neg_answered) / len(neg), 4)
    return out


def paired(rows_a: Iterable[dict], rows_b: Iterable[dict]) -> dict:
    """b minus a, end-to-end on all shared visible questions, effective on those both answered."""
    a = {r["id"]: state(r) for r in rows_a if r["visible"]}
    b = {r["id"]: state(r) for r in rows_b if r["visible"]}
    ids = sorted(set(a) & set(b))
    e2e = metrics.paired_delta([float(a[i] or 0) for i in ids], [float(b[i] or 0) for i in ids])
    both = [i for i in ids if a[i] is not None and b[i] is not None]
    eff = metrics.paired_delta([float(a[i]) for i in both], [float(b[i]) for i in both])
    return {"end_to_end": e2e, "effective": eff}
