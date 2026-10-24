"""Report/export stats for data/sticker_dataset.

Usage:
    python scripts/sticker_dataset_report.py
    python scripts/sticker_dataset_report.py --review-csv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "data" / "sticker_dataset"


def load_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-csv", action="store_true", help="write review.csv")
    args = parser.parse_args()

    labels = load_jsonl(DATASET / "labels.jsonl")
    inbox = [p for p in (DATASET / "inbox").glob("*") if p.is_file()]
    images = [p for p in (DATASET / "images").glob("*") if p.is_file()]
    size = sum(p.stat().st_size for p in DATASET.rglob("*") if p.is_file()) if DATASET.exists() else 0

    emotions = Counter()
    sources = Counter()
    nsfw = 0
    for row in labels:
        emotions.update((row.get("labels") or {}).get("emotion") or [])
        sources[row.get("source", "unknown")] += 1
        if (row.get("labels") or {}).get("nsfw"):
            nsfw += 1

    stats = {
        "inbox": len(inbox),
        "labeled": len(labels),
        "images_dir": len(images),
        "size_mb": round(size / 1024 / 1024, 2),
        "sources": dict(sources),
        "emotions": dict(emotions.most_common()),
        "nsfw": nsfw,
        "unreviewed": sum(1 for r in labels if not r.get("reviewed")),
    }
    out = DATASET / "stats.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))

    if args.review_csv:
        path = DATASET / "review.csv"
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["id", "emotions", "intent", "text", "nsfw", "reviewed", "notes"])
            for row in labels:
                lab = row.get("labels") or {}
                writer.writerow([
                    row.get("id", ""),
                    "/".join(lab.get("emotion") or []),
                    lab.get("intent", ""),
                    lab.get("text", ""),
                    int(bool(lab.get("nsfw"))),
                    int(bool(row.get("reviewed"))),
                    row.get("notes", ""),
                ])
        print(f"review csv: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
