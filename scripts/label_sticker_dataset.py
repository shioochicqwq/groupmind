"""Label collected stickers with a vision model and organize them into the dataset.

Reads data/sticker_dataset/inbox/*, asks a vision model for structured labels
(taxonomy), moves the image to images/ and appends/merges labels.jsonl.

Usage:
    $env:MULTI_API_KEY / .env configured
    python scripts/label_sticker_dataset.py --limit 20
    python scripts/label_sticker_dataset.py --dry-run
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "data" / "sticker_dataset"
INBOX = DATASET / "inbox"
IMAGES = DATASET / "images"
LABELS = DATASET / "labels.jsonl"
META = DATASET / "inbox_meta.jsonl"
ENV = ROOT / ".env"
API_BASE = os.environ.get("MULTI_API_BASE", "https://<GATEWAY_HOST>/v1")
MODEL = os.environ.get("STICKER_LABEL_MODEL", "gemini-3.8-flash")
MAX_BYTES = 5 * 1024 * 1024

TAXONOMY = [
    "开心", "无语", "生气", "惊讶", "嘲笑", "委屈", "得意", "疑惑",
    "哭", "摆烂", "害怕", "尴尬", "敷衍", "其他",
]

PROMPT = f"""你是表情包数据集标注员。看这张图片，输出严格 JSON（不要 markdown 代码块）。
字段：
- caption: 客观画面描述（中文，≤60 字）
- emotion: 情绪数组，只能从 {TAXONOMY} 里选 0-3 个
- intent: 这张表情包想表达的意图/用途（中文短句，≤20 字）
- text: 图中可见文字（没有就空字符串）
- character: 角色/作品/来源（未知就空字符串）
- usage: 适合在什么聊天场景发（数组，0-3 个短语）
- nsfw: 是否色情/违规（true/false）
- confidence: 0-1
只输出 JSON。"""


def load_env(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip().strip("'\""))


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


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def call_vision(image_path: Path, api_key: str) -> dict:
    ext = image_path.suffix.lower().lstrip(".") or "jpeg"
    mime = "image/jpeg" if ext in {"jpg", "jpeg"} else f"image/{ext}"
    data = base64.b64encode(image_path.read_bytes()).decode()
    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}},
                ],
            }
        ],
    }
    req = urllib.request.Request(
        f"{API_BASE}/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        result = json.loads(resp.read().decode())
    text = result["choices"][0]["message"]["content"].strip()
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError(f"model returned no JSON: {text[:200]}")
    parsed = json.loads(match.group(0))
    if not isinstance(parsed.get("emotion"), list):
        parsed["emotion"] = []
    parsed["emotion"] = [e for e in parsed["emotion"] if e in TAXONOMY]
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--model", default="")
    args = parser.parse_args()

    load_env(ENV)
    api_key = os.environ.get("MULTI_API_KEY", "").strip()
    if not api_key:
        print("ERROR: MULTI_API_KEY missing (.env)")
        return 1
    global MODEL
    if args.model:
        MODEL = args.model

    INBOX.mkdir(parents=True, exist_ok=True)
    IMAGES.mkdir(parents=True, exist_ok=True)
    labels = {row.get("id"): row for row in load_jsonl(LABELS) if row.get("id")}
    meta = {row.get("id"): row for row in load_jsonl(META) if row.get("id")}

    candidates = [
        p for p in sorted(INBOX.iterdir())
        if p.is_file() and p.suffix.lower() in {".gif", ".jpg", ".jpeg", ".png", ".webp", ".bmp"}
        and p.stem not in labels
    ][: args.limit]
    if not candidates:
        print("no unlabeled images in inbox")
        return 0

    done = 0
    for path in candidates:
        if path.stat().st_size > MAX_BYTES:
            print(f"skip large: {path.name}")
            continue
        try:
            parsed = call_vision(path, api_key)
        except (urllib.error.URLError, ValueError, KeyError, json.JSONDecodeError) as exc:
            print(f"label failed: {path.name}: {exc}")
            continue
        image_id = path.stem
        rel = f"images/{path.name}"
        row = {
            "id": image_id,
            "file": rel,
            "sha256": image_id,
            "source": (meta.get(image_id) or {}).get("source", "unknown"),
            "umo_hash": (meta.get(image_id) or {}).get("umo_hash", ""),
            "sender_hash": (meta.get(image_id) or {}).get("sender_hash", ""),
            "collected_at": (meta.get(image_id) or {}).get("collected_at", ""),
            "signals": (meta.get(image_id) or {}).get("signals", {}),
            "is_sticker": True,
            "caption": parsed.get("caption", ""),
            "labels": {
                "emotion": parsed.get("emotion", []),
                "intent": parsed.get("intent", ""),
                "text": parsed.get("text", ""),
                "character": parsed.get("character", ""),
                "usage": parsed.get("usage", []) if isinstance(parsed.get("usage"), list) else [],
                "nsfw": bool(parsed.get("nsfw", False)),
            },
            "confidence": parsed.get("confidence", 0),
            "reviewed": False,
            "notes": "",
        }
        print(f"labeled: {path.name} -> {row['labels']['emotion']} / {row['labels']['intent']}")
        if args.dry_run:
            continue
        path.replace(IMAGES / path.name)
        labels[image_id] = row
        done += 1

    if not args.dry_run:
        write_jsonl(LABELS, list(labels.values()))
        print(f"done: {done} labeled, total {len(labels)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
