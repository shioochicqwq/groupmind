"""Looking something up on the web away from the group's session.

Search results and pages are long (one page was 65,000 characters). A separate short conversation without the
persona reads them and hands back a conclusion of a few hundred characters; only that enters the group's context.
With the conclusion comes what was searched and which pages were or were not read, and a number under which the
asker can come back: the helper then continues its own conversation, pages already read still in front of it.
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
PAGE_CHARS, ANSWER_CHARS, MAX_CALLS, KEPT = 12000, 1500, 6, 8
OUT_TOKENS = 4000   # per call, thinking included; 1,000 left a conclusion empty or cut off (2026-11-13)
REREAD = "这个网址在上面已经读过（结果见上文），不再重读。{}"
AGAIN = "上一步没有写出结论。不要再查，根据上面已经读到的内容直接写结论；确实没读到相关内容就写没查到。"
NOTHING = "没查到确认的信息（查询没有完成）。不要凭记忆补答案。"


def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {"name": name, "description": description,
                                             "parameters": {"type": "object", "properties": properties, "required": required}}}


TOOLS = [
    _fn("search_web", "联网搜索。支持 site: / after: / before: / lang: 等语法。need_content 为真时带回正文，结果很长，只在摘要不够时用。",
        {"query": {"type": "string"}, "count": {"type": "integer"}, "need_content": {"type": "boolean"}}, ["query"]),
    _fn("fetch_page", "读取一个网址的正文。有反爬的网站会换真实浏览器读，慢一些，这时还会带回页面里的链接。正文没给完时用 offset 接着读。",
        {"url": {"type": "string"}, "offset": {"type": "integer"}}, ["url"]),
]


def _chat(base_url: str, key: str, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", json.dumps(body).encode(),
                                 {"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _page_key(args: dict) -> tuple[str, int]:
    return str(args.get("url", "")).strip().rstrip("/"), int(args.get("offset") or 0)


def _reads(messages: list) -> dict[tuple[str, int], bool]:
    """Pages already read in this conversation (a follow-up continues one): page -> whether reading it failed."""
    asked = {c.get("id"): json.loads(c["function"].get("arguments") or "{}") for m in messages if m.get("role") == "assistant"
             for c in m.get("tool_calls") or [] if c.get("function", {}).get("name") == "fetch_page"}
    return {_page_key(asked[m["tool_call_id"]]): str(m.get("content", "")).startswith("失败")
            for m in messages if m.get("role") == "tool" and m.get("tool_call_id") in asked}


def _did(name: str, args: dict, out: str) -> str:
    """One line for the asker: what was tried and whether it gave anything."""
    if name == "search_web":
        got = f"{out.count(chr(10) + '   http') + out.startswith('1. ')} 条" if out.startswith("1. ") else "没有结果"
        return f"- 搜索「{str(args.get('query', ''))[:60]}」：{got}"
    bad = out.startswith(("失败", "页面没有", "网址必须", "这个位置之后"))
    return f"- 读 {str(args.get('url', ''))[:120]}：" + (f"没读到（{out.removeprefix('失败：').split('。')[0][-90:]}）" if bad else f"读到 {len(out)} 字")


async def run(question: str, *, model: str, base_url: str, llm_key: str, web_key: str, timeout: float,
              messages: list | None = None) -> tuple[str, dict, list]:
    """The conclusion, what it cost (model calls and tokens: uncached, cached, output; web calls; seconds; the steps taken)
    and the conversation, which can be passed back in to ask further."""
    used = {"calls": 0, "prompt": 0, "cached": 0, "completion": 0, "web_calls": 0, "steps": []}
    t0 = time.monotonic()
    said = f"现在是 {datetime.now(TZ):%Y-%m-%d %H:%M}（北京时间）。\n\n{question.strip()}"
    given = json.dumps(messages or [], ensure_ascii=False)
    hints = {h: n for h, n in web.site_notes(question).items() if f"关于 {h}" not in given}   # once per conversation
    if hints:
        said += "\n\n" + "\n".join(f"（关于 {h}：" + " ".join(n) + "）" for h, n in hints.items())
    messages = [*messages, {"role": "user", "content": said}] if messages else [{"role": "system", "content": SYSTEM}, {"role": "user", "content": said}]
    answer, retried = NOTHING, False
    read = _reads(messages)
    try:
        for step in range(MAX_CALLS + 1):   # one more call when a conclusion comes back empty
            left = timeout - (time.monotonic() - t0)
            if left <= 5:
                break
            body = {"model": model, "messages": messages, "max_tokens": OUT_TOKENS}
            if step < MAX_CALLS - 1 and not retried and left > 25:   # the last call has no tools: it has to conclude from what it read
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
                text = (msg.get("content") or "").strip()
                if "DSML" in text[:200]:   # with no tools offered the model may still write a tool call out as text
                    text = ""
                if not text and not retried:   # asked once more, without tools, to write down what it read
                    retried = True
                    messages.append({"role": "user", "content": AGAIN})
                    continue
                answer = text[:ANSWER_CHARS] or NOTHING
                messages.append({"role": "assistant", "content": answer})
                break
            messages.append(msg)
            for c in calls:
                try:
                    args = json.loads(c["function"].get("arguments") or "{}")
                    if c["function"]["name"] == "search_web":
                        out = await web.search(web_key, str(args.get("query", "")), int(args.get("count") or 8), bool(args.get("need_content")))
                    else:
                        key = _page_key(args)
                        if key in read:   # the same page again: no new load on the site (sites that block do so on quick repeats)
                            out = REREAD.format("上次没读到，短时间内重读多半还是读不到，换别的来源。" if read[key] else "")
                            used["steps"].append(f"- 重复读 {str(args.get('url', ''))[:120]}：没有再读")
                            messages.append({"role": "tool", "tool_call_id": c.get("id", ""), "content": out})
                            continue
                        out = await web.fetch(web_key, str(args.get("url", "")), int(args.get("offset") or 0))
                        read[key] = out.startswith("失败")
                    used["web_calls"] += 1
                    used["steps"].append(_did(c["function"]["name"], args, out))
                except (ValueError, TypeError, AttributeError):
                    out = "参数不对。"
                if len(out) > PAGE_CHARS:
                    out = out[:PAGE_CHARS] + f"\n（后面还有 {len(out) - PAGE_CHARS} 字，没有给出）"
                messages.append({"role": "tool", "tool_call_id": c.get("id", ""), "content": out})
    except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError) as e:
        answer, used["error"] = f"没查成（{type(e).__name__}）。不要凭记忆补答案。", type(e).__name__
    used["seconds"] = round(time.monotonic() - t0, 1)
    if messages[-1]["role"] != "assistant":   # cut short: the record still has to end with the helper speaking
        messages.append({"role": "assistant", "content": answer})
    return answer, used, messages


class Lookups:
    """The look-ups of one process. Each gets a number; asking again under that number continues its conversation."""

    def __init__(self, **route) -> None:   # model, base_url, llm_key, web_key, timeout
        self.route, self.kept, self.n = route, {}, 0

    async def ask(self, question: str, follow_up: str = "") -> tuple[str, dict]:
        before = self.kept.get(follow_up.strip().upper())
        answer, used, messages = await run(question, messages=before, **self.route)
        self.n += 1
        ref = f"L{self.n}"
        self.kept[ref] = messages
        for old in list(self.kept)[:-KEPT]:
            del self.kept[old]
        note = "（没找到要接着问的那一次，这是重新查的。）\n" if follow_up.strip() and before is None else ""
        steps = "\n".join(used["steps"]) or "- 没有搜索也没有读网页"
        return (f"{note}{answer}\n\n【查证过程】\n{steps}\n【编号】{ref}。结论不够用、或要它换个办法再查时，"
                f"再调一次并把 follow_up 填成 {ref}：它会接着这次查到的东西继续。"), used

