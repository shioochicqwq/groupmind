"""Web search and page reading. The key stays in this process.

Search goes through the DeepSeek tool endpoint. A page is read through layers, cheapest first: the DeepSeek
fetch endpoint, then the project's own reader (plugins/astrbot_plugin_web_reader: plain request -> browser
fingerprint -> real Chrome), which gets past bot checks the endpoint cannot and also returns the page's links.
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import logging
from pathlib import Path
import urllib.error
import urllib.request

SEARCH_URL = "https://api.deepseek.com/v1/tools/search"
FETCH_URL = "https://api.deepseek.com/v1/tools/fetch"
READ_CHARS, READ_LINKS, IDLE_S = 9000, 40, 180   # per call; the browser is closed after this long without a page
log = logging.getLogger(__name__)
_browser = None          # started on the first page that needs it
_sites = None            # what is known per site (the reader's sites.py); set up with the browser
_closing: asyncio.TimerHandle | None = None
# Set by the host around a tool call that may hand the group over to a new session (bothost/handoff.py):
# awaited with a kind ("l3": the request tier failed and the browser is next; "known_l3": a site known to need it)
# and the address, before the browser is started. Nothing else here knows about sessions.
ESCALATE: contextvars.ContextVar = contextvars.ContextVar("escalate", default=None)
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


def use_browser(profile_dir: str, executable: str = "", xvfb: str = "Xvfb", timezone: str = "") -> bool:
    """Let page reading escalate to a real browser. False when the browser library is not installed."""
    global _browser
    from plugins.astrbot_plugin_web_reader import browser as br
    if not br.available():
        return False
    global _sites
    learned = str(Path(profile_dir).parent / "web-sites.json")   # next to the profile; the shipped defaults are in the reader's sites.json
    _browser = br.Browser(br.BrowserConfig(profile_dir=profile_dir, executable_path=executable, xvfb_command=xvfb, timezone=timezone,
                                           sites_file=learned))
    _sites = _browser.sites
    return True


def site_notes(text: str) -> dict[str, list[str]]:
    """Hints for the sites a question names, from the reader's sites.json."""
    global _sites
    if _sites is None:
        from plugins.astrbot_plugin_web_reader.sites import Sites
        _sites = Sites()
    return _sites.notes(text)


def _close_later() -> None:
    global _closing
    if _closing:
        _closing.cancel()
    loop = asyncio.get_running_loop()
    _closing = loop.call_later(IDLE_S, lambda: loop.create_task(_browser.close()))


async def cookies_file(url: str, folder: str) -> str:
    """The browser's cookies for this page's site as a cookies.txt in `folder`, for a downloader the site refuses.
    The page is opened first, so a site visited for the first time has given its visitor cookies. Empty without a browser."""
    if _browser is None:
        return ""
    try:
        page = await _browser.new_page()
        try:
            await _browser.load(page, url)
            await _browser.settle(page)
            found = await (await _browser.context()).cookies(url)
        finally:
            await page.close()
    finally:
        _close_later()
    if not found:
        return ""
    rows = ["\t".join([c["domain"], "TRUE" if c["domain"].startswith(".") else "FALSE", c["path"], "TRUE" if c["secure"] else "FALSE",
                       str(int(c["expires"])) if c.get("expires", -1) > 0 else "0", c["name"], c["value"]]) for c in found]
    path = Path(folder) / "cookies.txt"
    path.touch(mode=0o600)
    path.write_text("# Netscape HTTP Cookie File\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return str(path)


async def _read_local(url: str, offset: int, browser_only: bool = False) -> str:
    """The page through the reader's tiers: text from `offset` and the first links. Raises when it cannot be read."""
    from plugins.astrbot_plugin_web_reader.reader import extract, format_result
    from plugins.astrbot_plugin_web_reader.tiers import read_html
    hook = ESCALATE.get()
    try:
        final, ctype, raw, how = await read_html(url, (_browser,), before_browser=(lambda: hook("l3", url)) if hook and not browser_only else None,
                                                 browser_only=browser_only)
    finally:
        if _browser is not None:
            _close_later()
    if "html" not in ctype.lower() and "text" not in ctype.lower():
        raise ValueError(f"content type {ctype}")
    data = await asyncio.to_thread(extract, raw, final, offset, READ_CHARS, 0, READ_LINKS)
    if not data["total"]:
        raise ValueError("no text")
    return (how + "\n" if how else "") + format_result(data)


async def fetch(key: str, url: str, offset: int = 0) -> str:
    """The page's text from `offset`. The endpoint first; what it cannot read goes up the reader's tiers.
    A site the endpoint failed on and the reader read is remembered, and later pages there skip the endpoint."""
    url, offset = url.strip(), max(0, int(offset or 0))
    if not url.lower().startswith(("http://", "https://")) or len(url) > 8192:
        return "网址必须是 http 或 https 开头的有效地址。"
    browser_only = _browser is not None and _sites is not None and _sites.has("browser_first", url)
    if browser_only and (hook := ESCALATE.get()):
        await hook("known_l3", url)
    skip = browser_only or _sites is not None and _sites.has("local_first", url)
    first = "没有配置读取接口" if not key else "跳过了读取接口（已知它读不了这个站）" if skip else ""
    if not first:
        data = await _call(FETCH_URL, key, {"url": url})
        if not isinstance(data, str) and (content := str(data.get("content") or "")):
            more = f"（正文共 {len(content)} 字，这里从第 {offset} 字起）\n" if offset or len(content) > READ_CHARS else ""
            return f"# {data.get('title', '')}\n{more}\n{content[offset:]}" if content[offset:] else "这个位置之后没有正文了。"
        first = data.removeprefix("失败：").split("。")[0] if isinstance(data, str) else "读取接口没取到正文"
    try:
        page = await _read_local(url, offset, browser_only)
    except Exception as e:  # noqa: BLE001 - the tool has to answer with a sentence
        log.info("reader could not read the page either: %r", e)
        return f"失败：{first}；换本机和浏览器读也没成：{str(e) or type(e).__name__}。不要凭记忆补内容。"
    if key and not skip and _sites is not None:
        _sites.add("local_first", url)
    if not browser_only and _sites is not None and page.startswith("（经"):   # the request tier did not get it, a browser did
        _sites.add("browser_first", url)
    return page
