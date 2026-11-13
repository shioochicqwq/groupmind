"""Looking something up on the web away from the group's session.

Search results and pages are long (one page was 65,000 characters). A separate short conversation without the
persona reads them and hands back a conclusion of a few hundred characters; only that enters the group's context.
"""
from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from . import web
from .store import TZ

SYSTEM = (Path(__file__).parent / "prompt_lookup.md").read_text(encoding="utf-8").strip()
PAGE_CHARS, ANSWER_CHARS, MAX_CALLS = 12000, 800, 6
NOTHING = "没查到确认的信息（查询没有完成）。不要凭记忆补答案。"


def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {"name": name, "description": description,
                                             "parameters": {"type": "object", "properties": properties, "required": required}}}


TOOLS = [
    _fn("search_web", "联网搜索。支持 site: / after: / before: / lang: 等语法。need_content 为真时带回正文，结果很长，只在摘要不够时用。",
        {"query": {"type": "string"}, "count": {"type": "integer"}, "need_content": {"type": "boolean"}}, ["query"]),
    _fn("fetch_page", "读取一个网址的正文。", {"url": {"type": "string"}}, ["url"]),
]


def _chat(base_url: str, key: str, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", json.dumps(body).encode(),
                                 {"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


async def run(question: str, *, model: str, base_url: str, llm_key: str, web_key: str, timeout: float) -> tuple[str, dict]:
    """The conclusion and what it cost: model calls and tokens (uncached, cached, output), web calls, seconds."""
    used = {"calls": 0, "prompt": 0, "cached": 0, "completion": 0, "web_calls": 0}
    t0 = time.monotonic()
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"现在是 {datetime.now(TZ):%Y-%m-%d %H:%M}（北京时间）。\n\n{question.strip()}"}]
    answer = NOTHING
    try:
        for step in range(MAX_CALLS):
            left = timeout - (time.monotonic() - t0)
            if left <= 5:
                break
            body = {"model": model, "messages": messages, "max_tokens": 1000}
            if step < MAX_CALLS - 1:   # the last call has no tools: it has to conclude from what it read
                body["tools"] = TOOLS
            data = await asyncio.to_thread(_chat, base_url, llm_key, body, left)
            u = data.get("usage") or {}
            cached = int(u.get("prompt_cache_hit_tokens") or (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
            used["calls"] += 1
            used["prompt"] += int(u.get("prompt_tokens") or 0) - cached
            used["cached"] += cached
            used["completion"] += int(u.get("completion_tokens") or 0)
            msg = data["choices"][0]["message"]
            calls = msg.get("tool_calls") or []
            if not calls:
                answer = (msg.get("content") or "").strip()[:ANSWER_CHARS] or NOTHING
                break
            messages.append(msg)
            for c in calls:
                try:
                    args = json.loads(c["function"].get("arguments") or "{}")
                    if c["function"]["name"] == "search_web":
                        out = await web.search(web_key, str(args.get("query", "")), int(args.get("count") or 8), bool(args.get("need_content")))
                    else:
                        out = await web.fetch(web_key, str(args.get("url", "")))
                    used["web_calls"] += 1
                except (ValueError, TypeError, AttributeError):
                    out = "参数不对。"
                if len(out) > PAGE_CHARS:
                    out = out[:PAGE_CHARS] + f"\n（后面还有 {len(out) - PAGE_CHARS} 字，没有给出）"
                messages.append({"role": "tool", "tool_call_id": c.get("id", ""), "content": out})
    except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError) as e:
        answer, used["error"] = f"没查成（{type(e).__name__}）。不要凭记忆补答案。", type(e).__name__
    used["seconds"] = round(time.monotonic() - t0, 1)
    return answer, used
