"""Report context/token usage and memory footprint for the local bot.

Reads AstrBot's conversation list (token_usage per conversation) and the
memory_beyond data directory (if installed), so token-tuning changes can be
compared before/after.

Usage:
    $env:ASTRBOT_DASHBOARD_PASSWORD='...'; python scripts/context_report.py
    python scripts/context_report.py --json           # machine-readable
    python scripts/context_report.py --json --out tmp/context-baseline.json
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
MEMORY_DIR = ROOT / "data" / "plugin_data" / "astrbot_plugin_memory_beyond"


def post_json(base: str, path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


def get_json(base: str, path: str, token: str) -> dict:
    req = urllib.request.Request(base + path, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


def memory_footprint() -> dict:
    if not MEMORY_DIR.is_dir():
        return {"installed": False}
    files = [p for p in MEMORY_DIR.rglob("*.md") if p.is_file()]
    total = sum(p.stat().st_size for p in files)
    return {
        "installed": True,
        "files": len(files),
        "bytes": total,
        "top": sorted(
            ({"path": str(p.relative_to(MEMORY_DIR)), "bytes": p.stat().st_size} for p in files),
            key=lambda x: x["bytes"],
            reverse=True,
        )[:10],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dashboard", default="http://127.0.0.1:6185")
    parser.add_argument("--username", default="astrbot")
    parser.add_argument(
        "--password", default=os.environ.get("ASTRBOT_DASHBOARD_PASSWORD", "")
    )
    parser.add_argument("--json", action="store_true", help="print JSON instead of table")
    parser.add_argument("--out", default="", help="also write result JSON to this path")
    args = parser.parse_args()

    if not args.password:
        print("ERROR: set ASTRBOT_DASHBOARD_PASSWORD")
        return 1

    try:
        login = post_json(
            args.dashboard, "/api/auth/login",
            {"username": args.username, "password": args.password},
        )
        token = login["data"]["token"]
        conversations = get_json(
            args.dashboard, "/api/v1/conversations?page=1&page_size=200", token
        )["data"]["conversations"]
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:300]}")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}")
        return 1

    rows = []
    for conv in conversations:
        info = conv.get("umo_info") or {}
        rows.append(
            {
                "umo": info.get("umo", conv.get("user_id", "")),
                "type": info.get("message_type", ""),
                "token_usage": int(conv.get("token_usage") or 0),
                "updated_at": conv.get("updated_at"),
            }
        )
    rows.sort(key=lambda r: r["token_usage"], reverse=True)

    cfg_path = ROOT / "data" / "cmd_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
    result = {
        "conversations": rows,
        "total_tokens": sum(r["token_usage"] for r in rows),
        "config": {
            "group_message_max_cnt": cfg["provider_ltm_settings"].get("group_message_max_cnt"),
            "group_message_history_max_cnt": cfg["provider_ltm_settings"].get(
                "group_message_history_max_cnt"
            ),
            "compression": cfg["agent_runner"]["config"].get("compression"),
            "computer_use_runtime": cfg["provider_settings"].get("computer_use_runtime"),
        },
        "memory": memory_footprint(),
    }

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"{'tokens':>8}  {'type':<14} umo")
    for row in rows:
        print(f"{row['token_usage']:>8}  {row['type']:<14} {row['umo']}")
    print(f"\ntotal conversations: {len(rows)}, total tokens: {result['total_tokens']}")
    m = result["memory"]
    if m.get("installed"):
        print(f"memory files: {m['files']}, bytes: {m['bytes']}")
    else:
        print("memory_beyond: not installed")
    print(f"ICL max: {result['config']['group_message_max_cnt']}, "
          f"runtime: {result['config']['computer_use_runtime']}")
    comp = result["config"]["compression"] or {}
    print(f"compression: max_turns={comp.get('max_turns')} "
          f"strategy={comp.get('overflow_strategy')} "
          f"fallback={comp.get('fallback_max_tokens')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
