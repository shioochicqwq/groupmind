"""Merge colours that adjacent batches made twice in their 20-message overlap (fix 1, 2026-11-05).

Coloring runs in batches of 150 with 20 overlapping messages. Each overlap is coloured by both
batches, so the same micro-context often appears as two colours, which then compete for
retrieval slots. A colour from batch b and one from batch b+1 are merged when they share
overlap messages and those shared messages are at least half of the smaller colour's part of
the overlap. Merging is transitive (a context can run across several batches). The merged
colour keeps every message of both, in time order; its summary joins both summaries; the old
ids are kept in `merged_from`. Nothing else changes and no model is called.

Results after this fix are a different condition from every experiment run on the original
colours; the output is a new file next to the original, never a replacement.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from bench import coloring, realdata
from bench.tasks.real_tasks import clean_messages

VERSION = "merged-v1"
DEDUP_VERSION = "dedup-v1"
THRESHOLD = 0.5


def batch_of(color_id: str) -> int:
    return int(color_id[1:].split("c")[0])


def merge_overlaps(colors: list[dict], batches: list[list], threshold: float = THRESHOLD) -> tuple[list[dict], dict]:
    order = {m.msg_id: (m.timestamp, m.msg_id) for b in batches for m in b}
    by_batch: dict[int, list[int]] = defaultdict(list)
    for k, c in enumerate(colors):
        by_batch[batch_of(c["color_id"])].append(k)
    parent = list(range(len(colors)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    pairs = 0
    for b in range(len(batches) - 1):
        overlap = {m.msg_id for m in batches[b]} & {m.msg_id for m in batches[b + 1]}
        for x in by_batch.get(b, []):
            xs = set(colors[x]["msg_ids"]) & overlap
            if not xs:
                continue
            for y in by_batch.get(b + 1, []):
                ys = set(colors[y]["msg_ids"]) & overlap
                shared = xs & ys
                if shared and len(shared) >= threshold * min(len(xs), len(ys)):
                    parent[find(y)] = find(x)
                    pairs += 1
    groups: dict[int, list[int]] = defaultdict(list)
    for k in range(len(colors)):
        groups[find(k)].append(k)
    out = []
    for root in sorted(groups, key=lambda r: min(groups[r])):
        members = sorted(groups[root])
        if len(members) == 1:
            out.append(dict(colors[members[0]]))
            continue
        ids = sorted({i for k in members for i in colors[k]["msg_ids"]}, key=lambda i: order.get(i, (0, i)))
        summaries = list(dict.fromkeys(colors[k]["summary"] for k in members if colors[k]["summary"]))
        labels = list(dict.fromkeys(label for k in members for label in colors[k].get("labels", [])))
        out.append({"color_id": "+".join(colors[k]["color_id"] for k in members), "msg_ids": ids,
                    "summary": " / ".join(summaries), "labels": labels,
                    "merged_from": [colors[k]["color_id"] for k in members]})
    stats = {"version": VERSION, "threshold": threshold, "colors_before": len(colors), "colors_after": len(out),
             "merged_pairs": pairs, "merged_groups": sum(len(g) > 1 for g in groups.values()),
             "multi_before": _multi(colors), "multi_after": _multi(out)}
    return out, stats


def dedup_overlaps(colors: list[dict], batches: list[list], threshold: float = THRESHOLD) -> tuple[list[dict], dict]:
    """Fix 2: keep each overlap message only in the earlier batch's matching colour.

    Colours are not lengthened. For each matched pair (same rule as merge_overlaps), the shared
    overlap messages are removed from the later colour; a later colour left empty is dropped.
    """
    by_batch: dict[int, list[int]] = defaultdict(list)
    for k, c in enumerate(colors):
        by_batch[batch_of(c["color_id"])].append(k)
    drop: dict[int, set[str]] = defaultdict(set)
    for b in range(len(batches) - 1):
        overlap = {m.msg_id for m in batches[b]} & {m.msg_id for m in batches[b + 1]}
        for x in by_batch.get(b, []):
            xs = set(colors[x]["msg_ids"]) & overlap
            if not xs:
                continue
            for y in by_batch.get(b + 1, []):
                ys = set(colors[y]["msg_ids"]) & overlap
                shared = xs & ys
                if shared and len(shared) >= threshold * min(len(xs), len(ys)):
                    drop[y] |= shared
    out, removed_colors, removed_links = [], 0, 0
    for k, c in enumerate(colors):
        ids = [i for i in c["msg_ids"] if i not in drop.get(k, set())]
        removed_links += len(c["msg_ids"]) - len(ids)
        if not ids:
            removed_colors += 1
            continue
        out.append({**c, "msg_ids": ids} if len(ids) != len(c["msg_ids"]) else dict(c))
    stats = {"version": DEDUP_VERSION, "threshold": threshold, "colors_before": len(colors), "colors_after": len(out),
             "colors_dropped": removed_colors, "links_removed": removed_links,
             "multi_before": _multi(colors), "multi_after": _multi(out)}
    return out, stats


def _multi(colors: list[dict]) -> int:
    seen: dict[str, int] = defaultdict(int)
    for c in colors:
        for i in c["msg_ids"]:
            seen[i] += 1
    return sum(v > 1 for v in seen.values())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--model", default="gemini-3.8-flash-high")
    ap.add_argument("--mode", choices=("merge", "dedup"), default="dedup")
    args = ap.parse_args()
    messages = clean_messages(realdata.load_group(args.group))
    batches = coloring.batches(messages, 150, 20)
    src = args.out / f"colors.{args.model}.jsonl"
    colors = [json.loads(x) for x in src.read_text(encoding="utf-8").splitlines()]
    fixed, stats = (merge_overlaps if args.mode == "merge" else dedup_overlaps)(colors, batches)
    version = VERSION if args.mode == "merge" else DEDUP_VERSION
    dst = args.out / f"colors.{args.model}.{version}.jsonl"
    dst.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in fixed), encoding="utf-8")
    stats["source"] = src.name
    (args.out / f"colors.{args.model}.{version}.stats.json").write_text(json.dumps(stats, indent=1), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
