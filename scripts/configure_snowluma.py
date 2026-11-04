"""Write SnowLuma's OneBot and runtime config so it connects to AstrBot.

Idempotent: safe to re-run. Missing tokens are generated into ``.env`` and are
never printed. Existing SnowLuma config files are backed up before overwriting.

Writes ``config/onebot.json`` (global defaults) and ``config/runtime.json``
under the SnowLuma install dir. SnowLuma resolves ``config/`` from its working
directory, so it must be started from that dir (see deploy/windows/start-snowluma.ps1).

Usage:
    python scripts/configure_snowluma.py [--home C:\\SnowLuma] [--ws-url URL]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
ENV_EXAMPLE_PATH = ROOT / ".env.example"
TOKEN_NAMES = ("ONEBOT_WS_TOKEN", "SNOWLUMA_HTTP_TOKEN")
DEFAULT_HOME = r"C:\SnowLuma"
DEFAULT_WS_URL = "ws://127.0.0.1:6199/ws"
HTTP_PORT = 3000
WEBUI_PORT = 5099


def read_env(path: Path) -> dict[str, str]:
    """Parse simple KEY=VALUE lines."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip().strip("'\"")
    return values


def ensure_tokens() -> dict[str, str]:
    """Generate any missing token into .env; return the resulting values."""
    if not ENV_PATH.exists():
        shutil.copyfile(ENV_EXAMPLE_PATH, ENV_PATH)
        print(f"created: {ENV_PATH}")

    values = read_env(ENV_PATH)
    text = ENV_PATH.read_text(encoding="utf-8")
    for name in TOKEN_NAMES:
        if values.get(name):
            continue
        token = secrets.token_urlsafe(32)
        line = f"{name}={token}"
        text, count = re.subn(
            rf"^[ \t]*#?[ \t]*{name}[ \t]*=.*$", lambda _: line, text, flags=re.M
        )
        if not count:
            text = text.rstrip("\n") + f"\n{line}\n"
        values[name] = token
        print(f"generated: {name} (written to .env)")
    ENV_PATH.write_text(text, encoding="utf-8")
    return values


def write_json(path: Path, data: dict) -> None:
    """Write JSON, keeping a timestamped backup if the content changes."""
    content = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if path.is_file():
        if path.read_text(encoding="utf-8-sig") == content:
            print(f"unchanged: {path}")
            return
        backup = path.with_name(f"{path.name}.bak-{time.strftime('%Y%m%d%H%M%S')}")
        shutil.copy2(path, backup)
        print(f"backup: {backup}")
    path.write_text(content, encoding="utf-8")
    print(f"written: {path}")


def build_onebot_config(ws_url: str, ws_token: str, http_token: str) -> dict:
    return {
        "networks": {
            # Only healthcheck.py uses this; loopback + token.
            "httpServers": [
                {
                    "name": "http-local",
                    "enabled": True,
                    "host": "127.0.0.1",
                    "port": HTTP_PORT,
                    "path": "/",
                    "enableWebSocket": False,
                    "accessToken": http_token,
                    "messageFormat": "array",
                    "reportSelfMessage": False,
                }
            ],
            "httpClients": [],
            "wsServers": [],
            "wsClients": [
                {
                    "name": "astrbot",
                    "enabled": True,
                    "url": ws_url,
                    "role": "Universal",
                    "reconnectIntervalMs": 5000,
                    "accessToken": ws_token,
                    "messageFormat": "array",
                    "reportSelfMessage": False,
                }
            ],
        },
        # 默认开启时任何人发 #sl 都可能触发状态回复，不符合「像群友」的目标。
        "statusCommand": {"enabled": False},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", default="", help="SnowLuma install dir")
    parser.add_argument("--ws-url", default=DEFAULT_WS_URL)
    args = parser.parse_args()

    values = ensure_tokens()
    home = Path(args.home or values.get("SNOWLUMA_HOME") or DEFAULT_HOME)
    if not home.is_dir():
        raise SystemExit(f"SnowLuma dir not found: {home} (unpack the release first)")
    config_dir = home / "config"
    config_dir.mkdir(exist_ok=True)

    write_json(
        config_dir / "onebot.json",
        build_onebot_config(
            args.ws_url, values["ONEBOT_WS_TOKEN"], values["SNOWLUMA_HTTP_TOKEN"]
        ),
    )

    runtime_path = config_dir / "runtime.json"
    runtime = (
        json.loads(runtime_path.read_text(encoding="utf-8-sig"))
        if runtime_path.is_file()
        else {}
    )
    # hookAutoLoad 默认 false：不开的话重启后不会自动注入 QQ。
    runtime.update({"webuiPort": WEBUI_PORT, "webuiHost": "127.0.0.1", "hookAutoLoad": True})
    write_json(runtime_path, runtime)

    # 账号级文件会覆盖同名适配器；snapshot 模式下甚至完全不读全局配置。
    for path in sorted(config_dir.glob("onebot_*.json")):
        print(f"warning: account config may override global settings: {path}")


if __name__ == "__main__":
    main()
