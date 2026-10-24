"""Sticker dataset storage helpers (no AstrBot imports, testable)."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

DATASET_DIR_NAME = "sticker_dataset"
MAX_BYTES = 5 * 1024 * 1024
IMAGE_EXTS = {".gif", ".jpg", ".jpeg", ".png", ".webp", ".bmp"}
STICKER_SUMMARIES = ("动画表情", "mface", "sticker")


def dataset_root(base: Path) -> Path:
    return base / DATASET_DIR_NAME


def ensure_layout(root: Path) -> dict[str, Path]:
    paths = {
        "root": root,
        "inbox": root / "inbox",
        "images": root / "images",
        "rejected": root / "rejected",
        "meta": root / "inbox_meta.jsonl",
        "labels": root / "labels.jsonl",
        "stats": root / "stats.json",
    }
    for key in ("inbox", "images", "rejected"):
        paths[key].mkdir(parents=True, exist_ok=True)
    return paths


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()[:16]


def normalize_ext(suffix: str) -> str:
    suffix = (suffix or "").lower()
    return suffix if suffix in IMAGE_EXTS else ".img"


def infer_ext(name: str, mime: str = "") -> str:
    suffix = Path(name or "").suffix.lower()
    if suffix in IMAGE_EXTS:
        return suffix
    mime_map = {
        "image/gif": ".gif",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/bmp": ".bmp",
    }
    return mime_map.get((mime or "").lower(), ".img")


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def append_meta(path: Path, meta: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(meta, ensure_ascii=False) + "\n")


def existing_ids(root: Path) -> set[str]:
    ids = {r.get("id") for r in load_jsonl(root / "labels.jsonl") if r.get("id")}
    ids.update(p.stem for p in (root / "inbox").glob("*") if p.is_file())
    ids.update(p.stem for p in (root / "images").glob("*") if p.is_file())
    return ids


def has_sticker_signal(signals: dict) -> bool:
    if not signals:
        return False
    if int(signals.get("sub_type") or 0) == 1:
        return True
    summary = str(signals.get("summary") or "").lower()
    return any(s in summary for s in STICKER_SUMMARIES)


def save_image(
    root: Path,
    data: bytes,
    source: str,
    signals: dict,
    umo: str,
    sender_id: str,
    manual: bool = False,
) -> tuple[str, bool]:
    """Save image bytes into inbox; returns (image_id, is_new)."""
    paths = ensure_layout(root)
    image_id = sha256_bytes(data)
    if image_id in existing_ids(root):
        return image_id, False
    ext = infer_ext(signals.get("file", ""), signals.get("mime", ""))
    target = paths["inbox"] / f"{image_id}{ext}"
    target.write_bytes(data)
    meta = {
        "id": image_id,
        "file": f"inbox/{target.name}",
        "source": source,
        "manual": manual,
        "umo_hash": _hash_text(umo or ""),
        "sender_hash": _hash_text(sender_id or ""),
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "signals": signals or {},
        "sticker_signal": has_sticker_signal(signals or {}),
    }
    append_meta(paths["meta"], meta)
    return image_id, True
