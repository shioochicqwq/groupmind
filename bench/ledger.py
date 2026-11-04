"""Experiment ledger: one row per arm, with its conditions and results.

Rows live outside the repository (runs/ledger.jsonl). `table` exports metrics only, with
groups shown by split name, so the export can sit in docs/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Keys every arm should state, so rows from different experiments line up in one table.
CONDITION_KEYS = (
    "index", "chunking", "tokenizer", "top_k", "filter", "filter_view", "feed", "budget_chars",
    "model_main", "model_filter", "judge", "seed",
)


def fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12] if path.exists() else ""


def code_version() -> dict:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True).stdout

    diff = git("diff", "HEAD", "--", "bench") + git("ls-files", "--others", "--exclude-standard", "bench")
    return {"commit": git("rev-parse", "--short", "HEAD").strip(), "bench_diff": hashlib.sha256(diff.encode()).hexdigest()[:12]}


def row(experiment: str, arm: str, conditions: dict, metrics: dict, *, dataset: str, split: str,
        status: str = "valid", data: dict | None = None, note: str = "", when: str = "",
        tokens: dict | None = None, raw: str = "") -> dict:
    missing = [k for k in CONDITION_KEYS if k not in conditions]
    if missing:
        raise ValueError(f"{experiment}/{arm} does not state {missing}")
    return {
        "experiment": experiment, "arm": arm, "dataset": dataset, "split": split, "status": status,
        "when": when or time.strftime("%Y-%m-%d %H:%M"), "conditions": conditions, "metrics": metrics,
        "data": data or {}, "code": code_version(), "note": note,
        # {role: {calls, prompt, completion, ...}} from bench.usage; roles kept apart (筛选, 回答, 判官, 上色...).
        "tokens": tokens or {},
        # Per-question records (prompts, outputs, tokens), relative to the runs folder; real text, never in the repo.
        "raw": raw,
    }


def append(ledger: Path, rows: list[dict]) -> None:
    """Replace earlier rows of the same experiment and arm, keep everything else."""
    keep = []
    if ledger.exists():
        keys = {(r["experiment"], r["arm"]) for r in rows}
        keep = [r for r in map(json.loads, ledger.read_text(encoding="utf-8").splitlines())
                if (r["experiment"], r["arm"]) not in keys]
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in keep + rows), encoding="utf-8")


def cond(**kw) -> dict:
    base = dict.fromkeys(CONDITION_KEYS, "-")
    base.update(kw)
    return base


TABLE_COLUMNS = (
    ("实验", lambda r: r["experiment"]), ("组", lambda r: r["arm"]), ("数据", lambda r: f"{r['dataset']}/{r['split']}"),
    ("状态", lambda r: r["status"]),
    ("检索对象", lambda r: r["conditions"]["index"]), ("切块", lambda r: r["conditions"]["chunking"]),
    ("切词", lambda r: r["conditions"]["tokenizer"]), ("筛选", lambda r: r["conditions"]["filter"]),
    ("筛选看到", lambda r: r["conditions"]["filter_view"]), ("交给模型", lambda r: r["conditions"]["feed"]),
    ("预算(字)", lambda r: r["conditions"]["budget_chars"]),
    ("题数", lambda r: r["metrics"].get("n", "")),
    ("准确率", lambda r: pct(r["metrics"].get("accuracy"))),
    ("95% CI", lambda r: ci(r["metrics"].get("accuracy_ci95"))),
    ("R@10", lambda r: pct(r["metrics"].get("R@10"))),
    ("拒答", lambda r: pct(r["metrics"].get("refusal_when_absent"))),
    ("注入字数", lambda r: r["metrics"].get("avg_chars", "")),
    ("注入条数", lambda r: r["metrics"].get("avg_msgs", "")),
    ("筛选 token（入/出）", lambda r: tok(r, "筛选")),
    ("回答 token（入/出）", lambda r: tok(r, "回答")),
    ("判官 token（入/出）", lambda r: tok(r, "判官")),
    ("其他 token（入/出）", lambda r: tok(r, None)),
)

MAIN_ROLES = ("筛选", "回答", "判官")


def tok(r: dict, role: str | None) -> str:
    """Tokens the row needs for one role, or for every role outside the main three when role is None."""
    rows = [v for k, v in r.get("tokens", {}).items()
            if (k.split("|")[0] == role if role else k.split("|")[0] not in MAIN_ROLES)]
    if not rows:
        return ""
    p = sum(v["prompt"] for v in rows)
    c = sum(v["completion"] for v in rows)
    return f"{p / 1000:.0f}k/{c / 1000:.0f}k"


def pct(x) -> str:
    return "" if x is None else f"{100 * x:.1f}%"


def ci(x) -> str:
    return "" if not x else f"{100 * x[0]:.1f}–{100 * x[1]:.1f}"


def table(rows: list[dict]) -> str:
    head = "| " + " | ".join(c for c, _ in TABLE_COLUMNS) + " |"
    sep = "|" + "---|" * len(TABLE_COLUMNS)
    lines = [head, sep]
    for r in rows:
        lines.append("| " + " | ".join(str(f(r)).replace("|", "/") for _, f in TABLE_COLUMNS) + " |")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("table")
    t.add_argument("--ledger", type=Path, required=True)
    t.add_argument("--out", type=Path)
    t.add_argument("--experiment", default="")
    b = sub.add_parser("backfill")
    b.add_argument("--runs", type=Path, required=True)
    b.add_argument("--ledger", type=Path, required=True)
    args = ap.parse_args()
    if args.cmd == "backfill":
        from bench.ledger_backfill import backfill

        rows = backfill(args.runs)
        append(args.ledger, rows)
        print(len(rows), "rows")
        return 0
    rows = [json.loads(x) for x in args.ledger.read_text(encoding="utf-8").splitlines()]
    rows = [r for r in rows if r["experiment"].startswith(args.experiment)]
    text = table(rows)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
