"""Web search and page fetch through the DeepSeek tool endpoints. The key stays in this process."""
from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request

SEARCH_URL = "https://api.deepseek.com/v1/tools/search"
FETCH_URL = "https://api.deepseek.com/v1/tools/fetch"
REASONS = {401: "密钥无效", 402: "额度用完了", 403: "被拦截", 404: "页面读不到（被拦截、不存在或没有正文）", 408: "超时", 429: "请求太频繁"}


def _post(url: str, key: str, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


async def _call(url: str, key: str, body: dict, timeout: float = 30.0) -> dict | str:
    """The parsed reply, or a short sentence saying why there is none."""
    try:
        return await asyncio.to_thread(_post, url, key, body, timeout)
    except urllib.error.HTTPError as e:
        return f"失败：{REASONS.get(e.code, '服务出错' if e.code >= 500 else '请求出错')}（HTTP {e.code}）。不要凭记忆补内容。"
    except (OSError, ValueError) as e:
        return f"失败：网络或返回内容有问题（{type(e).__name__}）。不要凭记忆补内容。"


async def search(key: str, query: str, count: int = 8, need_content: bool = False) -> str:
    query = query.strip()
    if not 1 <= len(query) <= 128:
        return "搜索词要在 1 到 128 个字符之间。"
    data = await _call(SEARCH_URL, key, {"query": query, "count": max(1, min(int(count), 50)), "need_content": bool(need_content)})
    if isinstance(data, str):
        return data
    out = []
    for i, item in enumerate(data.get("results") or [], 1):
        out.append(f"{i}. {item.get('title', '')}\n   {item.get('url', '')}\n   发布时间：{item.get('date') or '不明'}\n"
                   f"   {item.get('summary') or item.get('snippet') or ''}" + (f"\n   正文：{item['content']}" if item.get("content") else ""))
    return "\n".join(out) if out else "搜索没有返回结果。换个说法再查，不要凭记忆补答案。"


async def fetch(key: str, url: str) -> str:
    url = url.strip()
    if not url.lower().startswith(("http://", "https://")) or len(url) > 8192:
        return "网址必须是 http 或 https 开头的有效地址。"
    data = await _call(FETCH_URL, key, {"url": url})
    if isinstance(data, str):
        return data
    content = str(data.get("content") or "")
    return f"# {data.get('title', '')}\n\n{content}" if content else "页面没有可提取的正文。"
