"""Health check for the local QQ bot stack (AstrBot + NapCat).

Works on Windows and Linux; stdlib only. Checks ports, AstrBot dashboard,
NapCat OneBot API and (optionally) providers/personas via the dashboard API.

Usage:
    python scripts/healthcheck.py
    $env:ASTRBOT_DASHBOARD_PASSWORD='...'; python scripts/healthcheck.py
    python scripts/healthcheck.py --dashboard http://127.0.0.1:6185 --napcat http://127.0.0.1:3000

Exit code 0 = all required checks passed, 1 = something failed.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEMORY_DIR = ROOT / "data" / "plugin_data" / "astrbot_plugin_memory_beyond"

PORTS = {
    "AstrBot WebUI": 6185,
    "AstrBot OneBot WS": 6199,
    "NapCat HTTP (OneBot)": 3000,
    "NapCat WebUI": 6099,
}

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))


def check_port(name: str, port: int) -> None:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=3):
            record(name, True, f"127.0.0.1:{port} open")
    except OSError as exc:
        record(name, False, f"127.0.0.1:{port} closed ({exc.__class__.__name__})")


def http_json(url: str, payload: dict | None = None, token: str = "") -> dict:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dashboard", default="http://127.0.0.1:6185")
    parser.add_argument("--napcat", default="http://127.0.0.1:3000")
    parser.add_argument("--username", default="astrbot")
    parser.add_argument(
        "--password", default=os.environ.get("ASTRBOT_DASHBOARD_PASSWORD", "")
    )
    args = parser.parse_args()

    for name, port in PORTS.items():
        check_port(name, port)

    # NapCat OneBot API: login info + online status
    account = ""
    try:
        login = http_json(f"{args.napcat}/get_login_info", {})
        info = login.get("data") or {}
        account = f"{info.get('user_id')} ({info.get('nickname')})"
        record("NapCat 账号登录", login.get("status") == "ok", account)
    except Exception as exc:  # noqa: BLE001
        record("NapCat 账号登录", False, f"{exc.__class__.__name__}: {exc}")

    try:
        status = http_json(f"{args.napcat}/get_status", {})
        record("NapCat 在线状态", bool((status.get("data") or {}).get("online")), str(status.get("data")))
    except Exception as exc:  # noqa: BLE001
        record("NapCat 在线状态", False, f"{exc.__class__.__name__}: {exc}")

    # AstrBot dashboard
    if not args.password:
        record("AstrBot Dashboard", False, "跳过（未提供 ASTRBOT_DASHBOARD_PASSWORD）")
    else:
        try:
            login = http_json(
                f"{args.dashboard}/api/auth/login",
                {"username": args.username, "password": args.password},
            )
            token = login["data"]["token"]
            bots = http_json(f"{args.dashboard}/api/v1/bots/stats", token=token)["data"]
            running = bots["summary"]["running"]
            total = bots["summary"]["total"]
            record("平台适配器", running == total and total > 0, f"{running}/{total} running")

            platforms = bots.get("platforms", [])
            napcat = next((p for p in platforms if p.get("id") == "napcat"), None)
            record(
                "OneBot 平台(状态)",
                bool(napcat) and napcat.get("status") == "running",
                (napcat or {}).get("status", "missing"),
            )

            providers = http_json(f"{args.dashboard}/api/v1/providers", token=token)["data"]
            enabled = [p["id"] for p in providers.get("providers", []) if p.get("enable")]
            record("LLM Providers", len(enabled) >= 2, f"{len(enabled)} enabled: {', '.join(enabled)}")

            personas = http_json(f"{args.dashboard}/api/v1/personas", token=token)["data"]
            ids = [p.get("persona_id") for p in personas]
            record("人格", "example" in ids, f"{len(ids)} personas: {', '.join(str(i) for i in ids)}")

            # Memory plugin (memory_beyond) + file/memory tools
            try:
                plugins = http_json(f"{args.dashboard}/api/v1/plugins", token=token)["data"]
                if isinstance(plugins, dict):
                    plugins = plugins.get("plugins") or []
                names = [
                    p.get("name") or p.get("root_dir_name") or ""
                    for p in plugins
                    if isinstance(p, dict)
                ]
                record(
                    "记忆插件 memory_beyond",
                    any("memory_beyond" in str(n) for n in names),
                    f"{len(names)} plugins loaded",
                )
            except Exception as exc:  # noqa: BLE001
                record("记忆插件 memory_beyond", False, f"{exc.__class__.__name__}: {exc}")

            try:
                tools = http_json(f"{args.dashboard}/api/v1/tools", token=token)["data"]
                tool_names = {t.get("name") for t in tools}
                record(
                    "文件工具",
                    "astrbot_file_read_tool" in tool_names,
                    "astrbot_file_read_tool registered",
                )
                record(
                    "记忆工具",
                    "memory_write" in tool_names and "memory_search" in tool_names,
                    "memory_write/memory_search registered",
                )
            except Exception as exc:  # noqa: BLE001
                record("文件/记忆工具", False, f"{exc.__class__.__name__}: {exc}")

            if MEMORY_DIR.is_dir():
                count = len(list(MEMORY_DIR.rglob("*.md")))
                record("记忆数据目录", True, f"{count} memory files")
            else:
                record("记忆数据目录", False, "missing data/plugin_data/astrbot_plugin_memory_beyond")

            # Context/token config sanity
            cfg_path = ROOT / "data" / "cmd_config.json"
            cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
            comp = cfg["agent_runner"]["config"]["compression"]
            icl = cfg["provider_ltm_settings"]["group_message_max_cnt"]
            runtime = cfg["provider_settings"].get("computer_use_runtime")
            record(
                "上下文配置",
                int(comp.get("fallback_max_tokens", 0)) >= 1_000_000 and icl <= 100,
                f"fallback={comp.get('fallback_max_tokens')}, ICL={icl}",
            )
            record("文件 runtime", runtime == "local", f"computer_use_runtime={runtime}")
        except urllib.error.HTTPError as exc:
            record("AstrBot Dashboard", False, f"HTTP {exc.code}")
        except Exception as exc:  # noqa: BLE001
            record("AstrBot Dashboard", False, f"{exc.__class__.__name__}: {exc}")

    print()
    width = max(len(name) for name, _, _ in results)
    failed = 0
    for name, ok, detail in results:
        mark = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
        print(f"[{mark}] {name.ljust(width)}  {detail}")
    print()
    print("stack OK" if failed == 0 else f"{failed} check(s) failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
