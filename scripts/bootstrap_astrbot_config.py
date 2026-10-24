"""Bootstrap local AstrBot config for NapCat (OneBot v11) + DeepSeek.

Idempotent: safe to re-run. Provider API keys are NOT written into the config
file; providers reference ``$VAR`` entries expanded by AstrBot, with real keys
in ``.env``. Exception: AstrBot's web-search key (``websearch_deepseek_key``)
has no env-ref support, so it is written literally from ``.env`` into the
gitignored ``data/cmd_config.json``.

Usage:
    python scripts/bootstrap_astrbot_config.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CFG_PATH = ROOT / "data" / "cmd_config.json"
ENV_PATH = ROOT / ".env"


def load_dotenv(path: Path) -> None:
    """Load simple KEY=VALUE lines into os.environ (existing env wins)."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip().strip("'\""))


def upsert(items: list[dict], item: dict) -> None:
    """Replace the entry with the same ``id`` or append it."""
    for existing in items:
        if existing.get("id") == item["id"]:
            existing.update(item)
            return
    items.append(item)


def main() -> None:
    load_dotenv(ENV_PATH)
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
    model_cfg = cfg.setdefault("agent_runner", {}).setdefault("config", {}).setdefault(
        "model", {}
    )
    model_cfg["provider_id"] = "deepseek"
    # 默认模型失败/限流时回退到聚合端点的快速模型。
    model_cfg["fallback_provider_ids"] = ["gemini-3.8-flash"]

    # --- 自定义 OpenAI 兼容聚合端点：多模型切换（gemini/claude/gpt） ---
    multi_base = os.environ.get("MULTI_API_BASE", "https://<GATEWAY_HOST>/v1")
    upsert(
        cfg.setdefault("provider_sources", []),
        {
            "id": "multi_source",
            "provider": "openai",
            "type": "openai_chat_completion",
            "provider_type": "chat_completion",
            "enable": True,
            "key": ["$MULTI_API_KEY"],
            "api_base": multi_base,
            "timeout": 120,
            "proxy": "",
            "custom_headers": {},
        },
    )
    for model_id in (
        "gemini-3.8-flash",
        "claude-sonnet-4-6",
        "claude-opus-4-6",
        "gpt-6-astra",
        "gpt-6.1-sol",
    ):
        upsert(
            cfg.setdefault("provider", []),
            {
                "id": model_id,
                "provider_source_id": "multi_source",
                "model": model_id,
                "modalities": [],
                "custom_extra_body": {},
                "enable": True,
            },
        )

    # --- 联网搜索：复用 DeepSeek 的 tools/search（无需额外 key） ---
    pset = cfg.setdefault("provider_settings", {})
    pset["web_search"] = True
    pset["websearch_provider"] = "deepseek"
    # 注意：AstrBot 的 websearch key 不支持 $ENV 引用，只能写实际值（data/ 已 gitignore）。
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    pset["websearch_deepseek_key"] = [deepseek_key] if deepseek_key else []
    pset["web_search_link"] = True

    # --- 多模态：用视觉模型给图片做 caption，文本模型也能"看图" ---
    pset["default_image_caption_provider_id"] = "gemini-3.8-flash"
    pset["image_caption_prompt"] = (
        "如果是表情包/贴纸：用一句话说明画面、图中文字、想表达的情绪和适用场景；"
        "如果是普通照片：简短描述画面关键内容。"
    )

    # --- 工具：本机 runtime 只开放 workspace 读写（读 QQ 附件/技能），禁执行 ---
    pset["computer_use_runtime"] = "local"
    pset["computer_use_require_admin"] = True
    workspace_policy = {
        "allow_execution": False,
        "allow_network": False,
        "filesystem_scope": "workspace",
    }
    pset["computer_use_local_permissions"] = {
        "member": dict(workspace_policy),
        "admin": dict(workspace_policy),
    }

    # --- 管理员：Dashboard 用户名 + QQ 主号（/provider、/model 等管理员指令需要） ---
    admins = cfg.setdefault("admins_id", ["astrbot"])
    for admin in ("astrbot", "<ADMIN_QQ>"):
        if admin not in admins:
            admins.append(admin)

    # --- 群聊上下文：被动携带最近群消息，便于整活/接梗 ---
    ltm = cfg.setdefault("provider_ltm_settings", {})
    ltm["group_message_history_enable"] = True
    ltm["group_message_history_max_cnt"] = 200
    ltm["group_icl_enable"] = True
    # 200 -> 100：ICL 是每轮固定 token 开销，降低后靠 memory_beyond 摘要 +
    # get_group_message_history 工具补历史（D-016 token 策略）。
    ltm["group_message_max_cnt"] = 100
    # 群聊上下文里的图片用视觉模型做描述（需要 image_caption_provider_id）
    ltm["image_caption"] = True
    ltm["image_caption_provider_id"] = "gemini-3.8-flash"
    ltm["active_reply"] = {
        # 测试群确认前保持关闭：当前小号所在群不是测试群，避免误插话。
        # 等有测试群后改为 True，并把群号填进 whitelist。
        "enable": False,
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

    # --- 上下文压缩交给 memory_beyond 插件接管（D-013） ---
    # 内置压缩没有关闭开关：把 token 路径的兜底窗口调到极大，轮数路径保持 -1，
    # 让内置压缩永不触发；实际压缩由 memory_beyond 在 0.70 阈值执行。
    compression = (
        cfg.setdefault("agent_runner", {})
        .setdefault("config", {})
        .setdefault("compression", {})
    )
    compression["fallback_max_tokens"] = 1_000_000_000
    compression["max_turns"] = -1

    # --- 工具声明省 token：先给轻量 schema，模型选定工具后再补参数 schema ---
    # 实测（2026-10-24）：skills_like 未降低工具声明（4110 vs 4066 tokens），
    # 反而多一次二阶段调用；恢复 full，token 优化靠压缩/ICL 裁剪（D-016）。
    misc = cfg.setdefault("agent_runner", {}).setdefault("config", {}).setdefault(
        "misc", {}
    )
    misc["tool_schema_mode"] = "full"

    CFG_PATH.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8-sig"
    )
    print(f"config written: {CFG_PATH}")


if __name__ == "__main__":
    main()
