"""Token usage per role (上色, 筛选, 回答, 判官, 出题, ...), recorded for every model call.

A cached call still counts toward what the experiment needs, and is marked as not newly spent,
so a replay of an old experiment recovers its usage from the cache.
"""
from __future__ import annotations

import json
import threading
from collections import defaultdict
from pathlib import Path

_lock = threading.Lock()
_events: list[dict] = []


def record(role: str, model: str, key: str, new: bool, prompt_tokens: int, completion_tokens: int) -> None:
    with _lock:
        _events.append({"role": role or "未标注", "model": model, "key": key, "new": new,
                        "prompt": prompt_tokens, "completion": completion_tokens})


def summary(events: list[dict] | None = None) -> dict[str, dict]:
    """Per role: calls, distinct prompts, tokens needed, and tokens newly spent in this process."""
    out: dict[str, dict] = defaultdict(lambda: {
        "calls": 0, "distinct": 0, "prompt": 0, "completion": 0, "new_calls": 0, "new_prompt": 0, "new_completion": 0,
        "models": set(),
    })
    seen: dict[str, set] = defaultdict(set)
    for e in _events if events is None else events:
        row = out[e["role"]]
        row["calls"] += 1
        row["models"].add(e["model"])
        if e["key"] in seen[e["role"]]:
            continue
        seen[e["role"]].add(e["key"])
        row["distinct"] += 1
        row["prompt"] += e["prompt"]
        row["completion"] += e["completion"]
        if e["new"]:
            row["new_calls"] += 1
            row["new_prompt"] += e["prompt"]
            row["new_completion"] += e["completion"]
    return {role: {**v, "models": sorted(v["models"])} for role, v in sorted(out.items())}


def write(path: Path, experiment: str) -> dict:
    data = {"experiment": experiment, "by_role": summary()}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data


def reset() -> None:
    with _lock:
        _events.clear()
