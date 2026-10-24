"""Evaluate the bot persona against scripted group-chat scenarios.

Uses AstrBot's WebChat API (same persona/provider pipeline as QQ, minus transport),
so we can tune personality/behaviour without a test group.

Outputs a transcript + simple style metrics; writes nothing to the repo.
Run:
    $env:ASTRBOT_DASHBOARD_PASSWORD='...'
    python scripts/eval_persona.py --provider deepseek
    python scripts/eval_persona.py --provider gemini-3.8-flash --compare

Exit code is always 0 (this is an evaluation, not a gate).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# Reuse the low-level WebChat helpers from smoke_llm.py (same directory).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from smoke_llm import get_json, post_json, stream_reply  # noqa: E402

SCENARIOS = [
    ("打招呼", "早上好"),
    ("闲聊天气", "今天好热啊，37 度"),
    ("群聊提问", "你们周末一般都干嘛"),
    ("接梗", "草，又加班到十点"),
    ("身份试探", "你是不是机器人啊"),
    ("长回答诱导", "给我讲讲量子力学，详细一点"),
    ("推荐", "推荐个游戏呗，最近无聊"),
    ("@ 场景", "@<BOT_NAME> 在吗"),
    ("短反应", "哈哈哈哈哈哈"),
    ("边界", "帮我写一篇 500 字的检讨书"),
]

AI_MARKERS = [
    "作为ai", "作为 ai", "语言模型", "我是ai", "作为人工智能", "人工智能助手",
    "chatgpt", "openai", "助手", "很高兴为您", "请问有什么可以帮",
]
MARKDOWN_MARKERS = ["```", "**", "###", "1. ", "2. ", "- ", "* "]


def analyze(reply: str) -> dict:
    low = reply.lower()
    return {
        "chars": len(reply),
        "long": len(reply) > 60,
        "ai_marker": next((m for m in AI_MARKERS if m in low), ""),
        "markdown": next((m for m in MARKDOWN_MARKERS if m in reply), ""),
        "newlines": reply.count("\n"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dashboard", default="http://127.0.0.1:6185")
    parser.add_argument("--username", default="astrbot")
    parser.add_argument(
        "--password", default=os.environ.get("ASTRBOT_DASHBOARD_PASSWORD", "")
    )
    parser.add_argument("--provider", default="deepseek")
    parser.add_argument(
        "--compare", action="store_true", help="also run with the default provider"
    )
    args = parser.parse_args()
    if not args.password:
        print("ERROR: set ASTRBOT_DASHBOARD_PASSWORD")
        return 1

    providers = [args.provider]
    if args.compare:
        providers.append("")  # default provider

    login = post_json(
        args.dashboard,
        "/api/auth/login",
        {"username": args.username, "password": args.password},
    )
    token = login["data"]["token"]

    for provider in providers:
        label = provider or "(default)"
        print(f"\n######## provider: {label} ########")
        stats = {"long": 0, "ai_marker": 0, "markdown": 0, "chars": 0, "replies": 0}
        for name, prompt in SCENARIOS:
            sid = get_json(args.dashboard, "/api/v1/chat/sessions/new", token)["data"][
                "session_id"
            ]
            payload = {"message": prompt, "session_id": sid}
            if provider:
                payload["selected_provider"] = provider
            reply, errors = stream_reply(args.dashboard, payload, token)
            m = analyze(reply)
            stats["replies"] += 1
            stats["chars"] += m["chars"]
            stats["long"] += int(m["long"])
            stats["ai_marker"] += int(bool(m["ai_marker"]))
            stats["markdown"] += int(bool(m["markdown"]))
            flags = []
            if m["long"]:
                flags.append(f"LONG({m['chars']})")
            if m["ai_marker"]:
                flags.append(f"AI:{m['ai_marker']}")
            if m["markdown"]:
                flags.append(f"MD:{m['markdown'].strip()!r}")
            if errors:
                flags.append(f"ERR:{errors}")
            print(f"\n[{name}] 用户: {prompt}")
            print(f"  -> {reply or '(empty)'}")
            if flags:
                print(f"  !! {', '.join(flags)}")
            time.sleep(0.3)

        n = max(1, stats["replies"])
        print(
            f"\n-- summary {label}: replies={stats['replies']} avg_chars={stats['chars']/n:.1f} "
            f"long={stats['long']} ai_marker={stats['ai_marker']} markdown={stats['markdown']}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
