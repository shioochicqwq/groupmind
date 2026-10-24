"""Create/update an AstrBot persona through the dashboard HTTP API.

The persona definition lives in ``config/personas/<name>.json`` (versioned in
git); this script upserts it into AstrBot's database so it survives restarts
and can be selected via ``agent_runner.config.persona.persona_id``.

Usage:
    set ASTRBOT_DASHBOARD_PASSWORD=...    (PowerShell: $env:...)
    python scripts/apply_persona.py --file config/personas/example.json

    # optional flags
    --dashboard http://127.0.0.1:6185 --username astrbot
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def request_json(
    base: str, path: str, method: str = "GET", token: str = "", payload=None
) -> dict:
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise SystemExit(f"HTTP {exc.code} on {method} {path}: {body}") from exc


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", default="config/personas/example.json")
    parser.add_argument("--dashboard", default="http://127.0.0.1:6185")
    parser.add_argument("--username", default="astrbot")
    parser.add_argument(
        "--password",
        default=os.environ.get("ASTRBOT_DASHBOARD_PASSWORD", ""),
        help="dashboard password (or set ASTRBOT_DASHBOARD_PASSWORD)",
    )
    args = parser.parse_args()

    if not args.password:
        raise SystemExit(
            "dashboard password required: pass --password or set ASTRBOT_DASHBOARD_PASSWORD"
        )

    spec = json.loads((ROOT / args.file).read_text(encoding="utf-8"))
    persona_id = spec["persona_id"]
    payload = {
        "persona_id": persona_id,
        "system_prompt": spec["system_prompt"],
        "begin_dialogs": spec.get("begin_dialogs") or [],
    }

    login = request_json(
        args.dashboard,
        "/api/auth/login",
        "POST",
        payload={"username": args.username, "password": args.password},
    )
    token = login["data"]["token"]

    api = "/api/v1"
    existing = request_json(args.dashboard, f"{api}/personas", token=token)
    ids = {p.get("persona_id") for p in existing.get("data", [])}

    if persona_id in ids:
        request_json(
            args.dashboard,
            f"{api}/personas/by-id",
            "PUT",
            token=token,
            payload=payload,
        )
        print(f"updated persona: {persona_id}")
    else:
        request_json(
            args.dashboard, f"{api}/personas", "POST", token=token, payload=payload
        )
        print(f"created persona: {persona_id}")

    # Remind the operator which config switch activates this persona.
    print(
        "activate with: agent_runner.config.persona.persona_id = "
        f'"{persona_id}" in data/cmd_config.json, then restart AstrBot'
    )


if __name__ == "__main__":
    sys.exit(main())
