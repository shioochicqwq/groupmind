"""The frozen retrieval path in one place: four routes, top-k each, global RRF, strict packing.

Overlap handling (D-032) is a switch, `config["overlap_dedup"]`:
  "none"         the original batch colours (scheme A; every experiment before D-032)
  "index"        B-index: each overlap message is indexed in the earlier batch's matching colour
                 only; the later colour is indexed without it. Matching is by message id, never by
                 text, so a real repeated message is never dropped.
  "route"        B-route: in each route, a block whose messages all appear in higher-ranked blocks
                 of that route is skipped and the next one moves up.
  "index+route"  B, the frozen version.

Whatever the switch, the injected units are the original local colour blocks (by colour id),
with their full messages, boundaries and order. Nothing here merges colours.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

from bench import chunking
from bench.color_fix import dedup_overlaps
from bench.embed import VectorIndex
from bench.memory_text import raw_blocks
from bench.retrievers import packing
from bench.retrievers.bm25 import BM25
from bench.run_embed_ablation import raw_text
from bench.schema import Block

MODES = ("none", "index", "route", "index+route")
# Routes are searched this deep before B-route skips covered blocks, so skipped slots can be refilled.
ROUTE_DEPTH = 30


def skip_covered(route: list[Block], k: int) -> list[Block]:
    """B-route: drop a block only when every one of its messages is already in a higher block."""
    seen: set[str] = set()
    out = []
    for b in route:
        ids = set(b.msg_ids)
        if ids and ids <= seen:
            continue
        out.append(b)
        seen |= ids
        if len(out) == k:
            break
    return out


@dataclass
class FrozenRetriever:
    indexes: list            # BM25 summary, BM25 raw, vector summary, vector raw
    by_color: dict[str, Block]  # injected units: the original colour blocks
    by_id: dict
    channel: str
    top_k: int
    budget: int
    mode: str

    def feed(self, blocks: list[Block]) -> list[str]:
        return raw_blocks(blocks, self.by_id)

    def routes(self, query: str, as_of: float) -> list[list[Block]]:
        depth = ROUTE_DEPTH if "route" in self.mode else self.top_k
        out = []
        for idx in self.indexes:
            hits = [self.by_color[b.block_id] for b, _ in idx.search(query, as_of, depth, self.channel) if b.block_id in self.by_color]
            out.append(skip_covered(hits, self.top_k) if "route" in self.mode else hits[: self.top_k])
        return out

    def retrieve(self, query: str, as_of: float) -> list[Block]:
        return packing.pack_in_order(packing.global_rrf(self.routes(query, as_of)), self.feed, self.budget)


def index_colors(colors: list[dict], batches: list[list], mode: str) -> tuple[list[dict], dict]:
    """The colours the indexes see. Only B-index changes them."""
    if mode not in MODES:
        raise ValueError(f"unknown overlap mode {mode!r}")
    if "index" in mode:
        return dedup_overlaps(colors, batches)
    return colors, {"version": "none"}


def build(ctx, config: dict, embedder, colors: list[dict], batches: list[list], role: str = "冻结版") -> tuple[FrozenRetriever, dict]:
    """ctx comes from run_abcd.prepare (original colours, tokenizer, messages)."""
    mode = config["overlap_dedup"]
    seen, stats = index_colors(colors, batches, mode)
    if seen is colors:
        summary, raw = ctx.summary_blocks, ctx.raw_color_blocks
        bm = [ctx.summary_index, ctx.raw_index]
        tag = "A"
    else:
        summary = chunking.from_colors(ctx.messages, seen, "summary")
        raw = chunking.from_colors(ctx.messages, seen, "raw")
        bm = [BM25(summary, ctx.tok), BM25(raw, ctx.tok)]
        tag = "B"
    # Vector raw text: the alias-rendered raw block, first 1000 characters (frozen embedding setting).
    mode_raw = config["embedding"].get("raw_mode", "alias")
    vec_raw = [replace(b, index_text=raw_text(b, ctx.by_id, ctx.summary_of, mode_raw)) for b in raw]
    # Cache keys depend only on text, so the role tag never changes which vectors are used.
    vs = VectorIndex(summary, embedder, f"层次|{tag}|摘要")
    vr = VectorIndex(vec_raw, embedder, f"层次|{tag}|原文块")
    r = FrozenRetriever(bm + [vs, vr], ctx.by_color, ctx.by_id, ctx.channel, config["top_k"], config["budget_chars"], mode)
    return r, stats


def block_manifest(group: str, colors_file: str, colors: list[dict], batches: list[list], messages, mode: str) -> list[dict]:
    """Stable references for layers built on top (events): one row per injected colour block.

    `msg_ids` are the block's full messages (what is injected); `indexed_msg_ids` are what the
    indexes see under the given mode. Ids are the research ids; bench/store maps them to rows.
    """
    by_id = {m.msg_id: m for m in messages}
    seen, _ = index_colors(colors, batches, mode)
    indexed = {c["color_id"]: c["msg_ids"] for c in seen}
    batch_of = {}
    for k, b in enumerate(batches):
        for m in b:
            batch_of.setdefault(m.msg_id, k)
    out = []
    for c in colors:
        part = sorted((by_id[i] for i in c["msg_ids"] if i in by_id), key=lambda m: (m.timestamp, m.msg_id))
        if not part:
            continue
        ids = [m.msg_id for m in part]
        out.append({
            "block_id": c["color_id"], "scope": f"group:{group}", "colors_file": colors_file,
            "batch": int(c["color_id"][1:].split("c")[0]),
            "start_ts": part[0].timestamp, "end_ts": part[-1].timestamp, "channel": part[-1].channel,
            "msg_ids": ids, "indexed_msg_ids": [i for i in ids if i in set(indexed.get(c["color_id"], []))],
            "labels": list(c.get("labels", [])),
        })
    return out


def write_manifest(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
