"""End-to-end LLM smoke test through AstrBot's WebChat API.

Validates: dashboard login -> WebChat session -> LLM reply, without needing
the QQ side. Useful to test a provider/model before touching group chat.

Usage:
    $env:ASTRBOT_DASHBOARD_PASSWORD='...'   # dashboard password
    python scripts/smoke_llm.py --provider deepseek
    python scripts/smoke_llm.py --provider gemini-3.8-flash --message "用一句话夸我"

Exit code 0 on a non-empty reply, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

REPLY_TIMEOUT = 180


def post_json(base: str, path: str, payload: dict, token: str = "") -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        base + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_json(base: str, path: str, token: str) -> dict:
    req = urllib.request.Request(base + path, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def stream_reply(base: str, payload: dict, token: str) -> tuple[str, list[str]]:
    """Send a WebChat message and collect the streamed plain-text reply."""
    req = urllib.request.Request(
        base + "/api/chat/send",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    chunks: list[str] = []
    completes: list[str] = []
    errors: list[str] = []
    with urllib.request.urlopen(req, timeout=REPLY_TIMEOUT) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            try:
                event = json.loads(line.removeprefix("data:").strip())
            except json.JSONDecodeError:
                continue
            etype = event.get("type")
            data = event.get("data")
            if etype == "plain" and isinstance(data, str):
                chunks.append(data)
            elif etype == "complete" and isinstance(data, str):
                completes.append(data)
            elif etype == "error":
                errors.append(str(data))
            elif etype == "end":
                break
    # Non-streaming replies arrive as a full "complete" event (the "plain"
    # events may repeat the same text), so prefer completes when present.
    reply = "\n".join(completes) if completes else "".join(chunks)
    return reply.strip(), errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dashboard", default="http://127.0.0.1:6185")
    parser.add_argument("--username", default="astrbot")
    parser.add_argument(
        "--password", default=os.environ.get("ASTRBOT_DASHBOARD_PASSWORD", "")
    )
    parser.add_argument("--provider", default="", help="selected_provider id, empty = default")
    parser.add_argument("--message", default="用一句话介绍你自己，别超过 30 字")
    parser.add_argument(
        "--followup",
        default="",
        help="optional second message in the SAME session (tests multi-turn context)",
    )
    args = parser.parse_args()

    if not args.password:
        print("ERROR: dashboard password required (--password or ASTRBOT_DASHBOARD_PASSWORD)")
        return 1

    try:
        login = post_json(
            args.dashboard,
            "/api/auth/login",
            {"username": args.username, "password": args.password},
        )
        token = login["data"]["token"]
        session = get_json(
            args.dashboard, "/api/v1/chat/sessions/new", token
        )["data"]
        sid = session["session_id"]
        payload = {"message": args.message, "session_id": sid}
        if args.provider:
            payload["selected_provider"] = args.provider
        reply, errors = stream_reply(args.dashboard, payload, token)
        followup_reply = ""
        if args.followup:
            payload2 = {"message": args.followup, "session_id": sid}
            if args.provider:
                payload2["selected_provider"] = args.provider
            followup_reply, errors2 = stream_reply(args.dashboard, payload2, token)
            errors.extend(errors2)
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:500]}")
        return 1
    except Exception as exc:  # noqa: BLE001 - CLI surface
        print(f"ERROR: {exc}")
        return 1

    print(f"provider: {args.provider or '(default)'}")
    print(f"reply   : {reply or '(empty)'}")
    if args.followup:
        print(f"followup: {args.followup}")
        print(f"reply2  : {followup_reply or '(empty)'}")
    if errors:
        print(f"errors  : {errors}")
    ok = reply and not errors and (not args.followup or followup_reply)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
