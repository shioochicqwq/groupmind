"""Per-question raw records: every input, output and token count behind a score.

Records hold real chat text, so they live beside the run outputs, outside the repository.
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from bench.llm import BatchLLM


def call_record(llm: BatchLLM, system: str, prompt: str | None) -> dict | None:
    """What one model call saw and said, looked up from the cache by its key."""
    if not prompt:
        return None
    key = llm._key(system, prompt)
    row = llm.cache.get(key, {})
    return {
        "model": llm.model, "key": key, "prompt": prompt, "output": row.get("text"),
        "prompt_tokens": row.get("prompt_tokens", 0), "completion_tokens": row.get("completion_tokens", 0),
    }


def write(path: Path, records: Iterable[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            n += 1
    return n


def arm_file(out: Path, experiment: str, arm: str) -> Path:
    safe = arm.replace(":", "_").replace(">", "").replace("/", "_").replace("@", "_at")
    return out / "raw" / experiment / f"{safe}.jsonl"
