"""Locate real groups by pseudonym; the mapping and the data live outside the repository."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from bench.datasets import qq_export
from bench.schema import Message, Visibility

DATA_DIR = Path(os.environ.get("QQBOT_BENCH_DATA", Path(__file__).resolve().parents[2] / "qqbot-data"))


def pseudonym(stem: str) -> str:
    return hashlib.sha256(stem.encode()).hexdigest()[:6]


def splits() -> dict[str, Visibility]:
    raw = json.loads((DATA_DIR / "selection.json").read_text(encoding="utf-8"))
    return {name: Visibility(v) for name, v in raw["groups"].items()}


def load_group(name: str) -> list[Message]:
    for path in (DATA_DIR / "reconciled").glob("*.jsonl"):
        if pseudonym(path.stem) == name:
            return qq_export.load(path, name)
    raise FileNotFoundError(name)
