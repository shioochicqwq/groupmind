"""Evaluate sticker understanding: generic caption prompt vs sticker-aware prompt.

Samples labeled stickers from data/sticker_dataset/labels.jsonl, asks a vision
model to infer emotion/intent under two prompts, compares against gold labels.

Usage:
    python scripts/eval_sticker_understanding.py --limit 10
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
LABELS = DATASET / "labels.jsonl"
ENV = ROOT / ".env"
API_BASE = os.environ.get("MULTI_API_BASE", "https://<GATEWAY_HOST>/v1")
MODEL = "gemini-3.8-flash"
TAXONOMY = [
    "开心", "无语", "生气", "惊讶", "嘲笑", "委屈", "得意", "疑惑",
    "哭", "摆烂", "害怕", "尴尬", "敷衍", "其他",
]

PROMPTS = {
    "generic": "用一句话描述这张图片。",
    "sticker_aware": (
        "这是聊天里的表情包/贴纸。用一句话说明：画面、图中文字、想表达的情绪和适用场景。"
    ),
}
ASK_JSON = (
    "另外只输出一个 JSON：{\"emotion\": 数组（从 "
    + "/".join(TAXONOMY)
    + " 中选 0-3 个）, \"intent\": 一句短意图}。不要输出其他内容。"
)


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
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return rows


def call(image_path: Path, prompt: str, api_key: str) -> dict:
    ext = image_path.suffix.lower().lstrip(".") or "jpeg"
    mime = "image/jpeg" if ext in {"jpg", "jpeg"} else f"image/{ext}"
    data = base64.b64encode(image_path.read_bytes()).decode()
    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt + "\n" + ASK_JSON},
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
        text = json.loads(resp.read().decode())["choices"][0]["message"]["content"]
    match = re.search(r"\{.*\}", text, re.S)
    return json.loads(match.group(0)) if match else {}


def overlap(a: list[str], b: list[str]) -> float:
    sa, sb = set(a or []), set(b or [])
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / max(1, len(sa | sb))


def char_jaccard(a: str, b: str) -> float:
    sa = {a[i:i + 2] for i in range(max(0, len(a) - 1))} or {a}
    sb = {b[i:i + 2] for i in range(max(0, len(b) - 1))} or {b}
    return len(sa & sb) / max(1, len(sa | sb))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    load_env(ENV)
    api_key = os.environ.get("MULTI_API_KEY", "").strip()
    if not api_key:
        print("ERROR: MULTI_API_KEY missing")
        return 1

    rows = [r for r in load_jsonl(LABELS) if (DATASET / r.get("file", "")).is_file()][
        : args.limit
    ]
    if not rows:
        print("no labeled stickers to evaluate")
        return 1

    totals = {name: {"emotion": 0.0, "intent": 0.0, "n": 0} for name in PROMPTS}
    for row in rows:
        gold = row.get("labels") or {}
        for name, prompt in PROMPTS.items():
            try:
                pred = call(DATASET / row["file"], prompt, api_key)
            except (urllib.error.URLError, json.JSONDecodeError, KeyError) as exc:
                print(f"skip {row['id'][:8]} {name}: {exc}")
                continue
            totals[name]["emotion"] += overlap(pred.get("emotion", []), gold.get("emotion", []))
            totals[name]["intent"] += char_jaccard(pred.get("intent", ""), gold.get("intent", ""))
            totals[name]["n"] += 1

    for name, t in totals.items():
        n = max(1, t["n"])
        print(f"{name}: emotion_overlap={t['emotion']/n:.2f} intent_jaccard={t['intent']/n:.2f} (n={t['n']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
