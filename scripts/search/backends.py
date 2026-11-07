"""Page readers behind one interface, for comparing them on the same cases.

read(url, offset) -> {ok, url, title, text, start, end, more, links: [(label, href)], error}
Text is cut into CHUNK-character pieces the same way for every backend, and every backend
returns all the links it found (the model gets them; the 60-link cap is web_reader's own).

  web_reader   the project's current plugin (requests + bs4, first 60 links in page order)
  mcp_fetch    the official MCP fetch server's extraction (readability + markdownify, robots.txt
               not checked here, as for a user-given URL); links are the ones left in the markdown
  crawl4ai     Crawl4AI with a headless browser (markdown + its internal/external link lists)
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
from functools import lru_cache
from pathlib import Path
from urllib.parse import urljoin

CHUNK = 6000
_MD_LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


def _page(url: str, title: str, full: str, links: list, offset: int) -> dict:
    end = min(len(full), offset + CHUNK)
    return {"ok": True, "url": url, "title": title, "text": full[offset:end], "start": offset, "end": end,
            "more": end < len(full), "links": links, "total_chars": len(full)}


@lru_cache(maxsize=256)
def _web_reader(url: str):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins" / "astrbot_plugin_web_reader"))
    import reader
    final, _ctype, body = reader.fetch(url)
    parts, off, d = [], 0, None
    while True:
        d = reader.extract(body, final, offset=off, limit=reader.MAX_LIMIT)
        parts.append(d["text"])
        if not d.get("more"):
            break
        off = d["end"]
    first = reader.extract(body, final)
    return final, first.get("title", ""), "".join(parts), tuple(first["links"])


@lru_cache(maxsize=256)
def _mcp_fetch(url: str):
    from mcp_server_fetch import server as s
    content, prefix = asyncio.run(s.fetch_url(url, s.DEFAULT_USER_AGENT_MANUAL))
    if prefix and "error" in prefix.lower() and not content:
        raise RuntimeError(prefix)
    links = tuple((label.strip(), urljoin(url, href)) for label, href in _MD_LINK.findall(content))
    return url, "", content, links


_C4: dict = {}


def _c4_crawler():
    """One event loop and one browser for the whole process; starting a browser per page is slow."""
    if "crawler" not in _C4:
        from crawl4ai import AsyncWebCrawler, BrowserConfig
        loop = asyncio.new_event_loop()
        # CRAWL4AI_CDP_URL: reuse a running Chromium (e.g. one started with --remote-debugging-port).
        cdp = os.environ.get("CRAWL4AI_CDP_URL", "")
        cfg = BrowserConfig(headless=True, verbose=False, **({"browser_mode": "cdp", "cdp_url": cdp} if cdp else {}))
        crawler = AsyncWebCrawler(config=cfg)
        loop.run_until_complete(crawler.start())
        _C4.update(loop=loop, crawler=crawler)
    return _C4["loop"], _C4["crawler"]


@lru_cache(maxsize=256)
def _crawl4ai(url: str):
    from crawl4ai import CacheMode, CrawlerRunConfig
    loop, crawler = _c4_crawler()
    r = loop.run_until_complete(crawler.arun(url, config=CrawlerRunConfig(cache_mode=CacheMode.BYPASS, verbose=False,
                                                                           page_timeout=30000)))
    if not r.success:
        raise RuntimeError(f"{r.status_code} {r.error_message}"[:200])
    md = r.markdown.raw_markdown if hasattr(r.markdown, "raw_markdown") else str(r.markdown)
    links = tuple((x.get("text", "").strip(), urljoin(url, x["href"])) for kind in ("internal", "external")
                  for x in (r.links or {}).get(kind, []) if x.get("href"))
    return r.url or url, (r.metadata or {}).get("title", ""), md, links


BACKENDS = {"web_reader": _web_reader, "mcp_fetch": _mcp_fetch, "crawl4ai": _crawl4ai}


def read(backend: str, url: str, offset: int = 0) -> dict:
    try:
        final, title, full, links = BACKENDS[backend](url)
        return _page(final, title, full, list(links), offset)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}
