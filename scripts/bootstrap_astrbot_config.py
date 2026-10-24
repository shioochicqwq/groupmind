"""Bootstrap local AstrBot config for NapCat (OneBot v11) + DeepSeek.

Idempotent: safe to re-run. API keys are NOT written into the config file;
instead the provider references the environment variable ``DEEPSEEK_API_KEY``
(AstrBot expands ``$VAR`` entries at load time). Put real keys in ``.env``.

Usage:
    python scripts/bootstrap_astrbot_config.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CFG_PATH = ROOT / "data" / "cmd_config.json"


def upsert(items: list[dict], item: dict) -> None:
    """Replace the entry with the same ``id`` or append it."""
    for existing in items:
        if existing.get("id") == item["id"]:
            existing.update(item)
            return
    items.append(item)


def main() -> None:
    # AstrBot reads/writes this file as utf-8-sig (BOM); match it.
    cfg = json.loads(CFG_PATH.read_text(encoding="utf-8-sig"))

    # --- 消息平台：OneBot v11 反向 WebSocket（NapCat 作为客户端接入） ---
    upsert(
        cfg.setdefault("platform", []),
        {
            "id": "napcat",
            "type": "aiocqhttp",
            "enable": True,
            "ws_reverse_host": "0.0.0.0",
            "ws_reverse_port": 6199,
            "ws_reverse_token": "",
        },
    )

    # --- 模型提供商：DeepSeek（key 从环境变量注入，见 .env.example） ---
    upsert(
        cfg.setdefault("provider_sources", []),
        {
            "id": "deepseek_source",
            "provider": "deepseek",
            "type": "openai_chat_completion",
            "provider_type": "chat_completion",
            "enable": True,
            "key": ["$DEEPSEEK_API_KEY"],
            "api_base": "https://api.deepseek.com/v1",
            "timeout": 120,
            "proxy": "",
            "custom_headers": {},
        },
    )
    upsert(
        cfg.setdefault("provider", []),
        {
            "id": "deepseek",
            "provider_source_id": "deepseek_source",
            "model": "deepseek-chat",
            "modalities": [],
            "custom_extra_body": {},
            "enable": True,
        },
    )
    cfg.setdefault("agent_runner", {}).setdefault("config", {}).setdefault("model", {})[
        "provider_id"
    ] = "deepseek"

    # --- 群聊上下文：被动携带最近群消息，便于整活/接梗 ---
    ltm = cfg.setdefault("provider_ltm_settings", {})
    ltm["group_message_history_enable"] = True
    ltm["group_message_history_max_cnt"] = 200
    ltm["group_icl_enable"] = True
    ltm["group_message_max_cnt"] = 200
    ltm["active_reply"] = {
        "enable": True,
        "method": "possibility_reply",
        # 主动插话概率：3%。先低后调，避免刷屏被群管理嫌弃。
        "possibility_reply": 0.03,
        # 留空 = 所有群生效；测试群确定后填入群号白名单。
        "whitelist": [],
    }

    # --- 群聊整活：分段回复更像真人；限流兜底防刷屏 ---
    platform_settings = cfg.setdefault("platform_settings", {})
    platform_settings["rate_limit"] = {"time": 60, "count": 20, "strategy": "stall"}
    segmented = platform_settings.setdefault("segmented_reply", {})
    segmented.update(
        {
            "enable": True,
            "only_llm_result": True,
            "words_count_threshold": 150,
            "interval": "1.5,3.5",
        }
    )

    # --- 人设：config/personas/example.json（scripts/apply_persona.py 写入 DB） ---
    cfg.setdefault("agent_runner", {}).setdefault("config", {}).setdefault(
        "persona", {}
    )["persona_id"] = "example"

    CFG_PATH.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8-sig"
    )
    print(f"config written: {CFG_PATH}")


if __name__ == "__main__":
    main()
