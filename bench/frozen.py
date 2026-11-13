"""The frozen retrieval version and the kept alternative, in one place (D-028, D-029, D-032).

Experiments before 2026-11-05 ran with the old vector settings (V0: no text_type, no
instruction). They are not re-run yet; when quota allows they are re-measured on FROZEN.
"""
from __future__ import annotations

from pathlib import Path

from bench.embed import AliyunEmbedder

INSTRUCT = "给定群聊里的一个问题，检索能回答这个问题的聊天记录"

# Four routes (keyword summary, keyword raw block, vector summary, vector raw block), top 5
# per route, global RRF k=60, strict packing into 1500 injected characters, raw blocks, no filter.
FROZEN = {
    "name": "V2",
    "colors": "colors.gemini-3.8-flash-high.jsonl",  # original batch colours; their boundaries are kept
    # D-032: overlap duplicates removed without merging. "index": each overlap message is indexed in
    # the earlier batch's matching colour only; "route": a block fully covered by higher blocks in a
    # route is skipped. Injected units stay the original blocks. Experiments before D-032 used "none".
    "overlap_dedup": "index+route",
    "routes": 4, "top_k": 5, "rrf_k": 60, "budget_chars": 1500, "feed": "raw blocks", "filter": False,
    "embedding": {"model": "qwen3.7-text-embedding-flash", "dim": 768, "asymmetric": True, "instruct": INSTRUCT,
                  "raw_text": "alias: content, first 1000 chars"},
}

# Kept, not frozen: the same settings on the larger model.
ALTERNATIVE = {**FROZEN, "name": "M1",
               "embedding": {**FROZEN["embedding"], "model": "qwen3.7-text-embedding"}}

# What every experiment before 2026-11-05 actually used.
LEGACY = {**FROZEN, "name": "V0", "overlap_dedup": "none",
          "embedding": {**FROZEN["embedding"], "asymmetric": False, "instruct": ""}}


def cache_file(config: dict, folder: Path) -> Path:
    e = config["embedding"]
    return (folder / "embed.aliyun.cache.jsonl" if config["name"] == "V0"
            else folder / f"embed.ablation.{e['model']}.{e['dim']}.cache.jsonl")


def embedder(config: dict, folder: Path) -> AliyunEmbedder:
    e = config["embedding"]
    return AliyunEmbedder(cache_file(config, folder), e["model"], e["dim"], e["asymmetric"], e["instruct"])
