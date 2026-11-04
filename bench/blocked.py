"""Questions whose answer call came back empty (mostly safety blocks) are marked and kept,
but left out of every statistic (user decision, 2026-11-04).

A question is marked when any arm, visible or not, got an empty answer for it. The list is
written once per run folder with a version, so later experiments keep the same denominator;
new blocks found later go into a new version instead of silently shrinking old tables.
"""
from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from pathlib import Path

from bench import metrics

QA_EXPERIMENTS = ("abcd", "vector", "packing", "depth", "s0")
FILE = "blocked_questions.json"
RULE = "任一方案、任一条件（可见或不可见）的回答调用返回空，就标记整道题；标记后保留，统计时排除"


def scan(folder: Path) -> dict[str, list[str]]:
    """question_id -> where the empty answers were, as experiment/arm|v (visible) or |a (absent)."""
    found: dict[str, list[str]] = {}
    for exp in QA_EXPERIMENTS:
        for path in sorted((folder / "raw" / exp).glob("*.jsonl")):
            for line in path.open(encoding="utf-8"):
                r = json.loads(line)
                answer = r.get("answer")
                if not isinstance(answer, dict) or (answer.get("output") or "").strip():
                    continue
                where = f"{exp}/{path.stem}|{'v' if r.get('visible') else 'a'}"
                found.setdefault(r["question_id"], []).append(where)
    return found


def write(folder: Path, version: int = 1) -> dict:
    found = scan(folder)
    data = {"version": version, "rule": RULE, "experiments": list(QA_EXPERIMENTS),
            "count": len(found), "questions": {q: sorted(v) for q, v in sorted(found.items())}}
    (folder / FILE).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data


def load(folder: Path) -> set[str]:
    path = folder / FILE
    return set(json.loads(path.read_text(encoding="utf-8"))["questions"]) if path.exists() else set()


def rescore(rows: Iterable[dict], blocked: set[str]) -> dict:
    """Arm metrics over the questions that were never blocked."""
    rows = [r for r in rows if r["id"] not in blocked]
    pos = [r for r in rows if r["visible"]]
    neg = [r for r in rows if not r["visible"]]
    out: dict = {"n": len(pos), "scoring": "排除拦截题"}
    if pos:
        acc = [float(r["correct"]) for r in pos]
        out["accuracy"] = round(sum(acc) / len(acc), 4)
        out["accuracy_ci95"] = [round(x, 3) for x in metrics.bootstrap_ci(acc)]
        low = [float(r["correct"]) for r in pos if r.get("overlap") == "low"]
        if low:
            out["accuracy_low_overlap"] = round(sum(low) / len(low), 4)
        if "gold_injected" in pos[0]:
            out["gold_injected"] = round(sum(r["gold_injected"] for r in pos) / len(pos), 4)
        if "chars" in pos[0]:
            out["avg_chars"] = round(sum(r["chars"] for r in pos) / len(pos))
    if neg and "refused" in neg[0]:
        out["refusal_when_absent"] = round(sum(r["refused"] for r in neg) / len(neg), 4)
        out["n_absent"] = len(neg)
    return out


def paired(rows_a: Iterable[dict], rows_b: Iterable[dict], blocked: set[str]) -> dict:
    """b minus a on the visible questions both arms answered, blocked ones left out."""
    a = {r["id"]: float(r["correct"]) for r in rows_a if r["visible"] and r["id"] not in blocked}
    b = {r["id"]: float(r["correct"]) for r in rows_b if r["visible"] and r["id"] not in blocked}
    ids = sorted(set(a) & set(b))
    return metrics.paired_delta([a[i] for i in ids], [b[i] for i in ids])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("folders", nargs="+", type=Path)
    for folder in ap.parse_args().folders:
        data = write(folder)
        print(folder.name, data["count"], "questions marked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
