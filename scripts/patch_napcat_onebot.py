"""Point NapCat's OneBot v11 config at AstrBot's reverse WebSocket server.

Idempotent: adds (or updates) a ``websocketClients`` entry named ``astrbot`` in
every ``onebot11*.json`` under the NapCat config directory.

Usage:
    python scripts/patch_napcat_onebot.py [NAPCAT_CONFIG_DIR] [WS_URL]
    # defaults: D:\\Apps\\NapCat\\config  ws://127.0.0.1:6199/ws
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

DEFAULT_CONFIG_DIR = Path(r"D:\Apps\NapCat\config")
DEFAULT_WS_URL = "ws://127.0.0.1:6199/ws"


def patch_file(path: Path, ws_url: str) -> bool:
    raw = path.read_text(encoding="utf-8-sig")
    data = json.loads(raw)
    network = data.setdefault("network", {})
    clients = network.setdefault("websocketClients", [])
    desired = {
        "name": "astrbot",
        "enable": True,
        "url": ws_url,
        "messagePostFormat": "array",
        "reportSelfMessage": False,
        "token": "",
        "debug": False,
    }
    for i, client in enumerate(clients):
        if client.get("name") == "astrbot":
            if clients[i] == desired:
                return False
            clients[i] = desired
            break
    else:
        clients.append(desired)

    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True


def main() -> None:
    config_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CONFIG_DIR
    ws_url = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_WS_URL
    paths = sorted(config_dir.glob("onebot11*.json"))
    if not paths:
        raise SystemExit(f"no onebot11*.json found in {config_dir}")
    for path in paths:
        changed = patch_file(path, ws_url)
        print(f"{'patched' if changed else 'unchanged'}: {path}")


if __name__ == "__main__":
    main()
