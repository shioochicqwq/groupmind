"""The escalation path for reading one page, free of the bot framework so any host can use it.

request with a browser's TLS fingerprint (curl_cffi; a plain request when it is not installed) -> real Chrome
-> Camoufox, each step only when the previous one hit a bot check or returned a nearly empty page. The
fingerprint request costs the same as a plain one (measured 2026-11-13) and passes some checks a plain one
does not, so the plain request is no longer tried first.
"""
from __future__ import annotations

import asyncio
import logging

from .reader import BotWall, FetchError, extract, fetch, fetch_impersonate

log = logging.getLogger(__name__)


def too_thin(ctype: str, raw: bytes, url: str) -> bool:
    """An HTML page whose main text is nearly empty: JS-rendered or a disguised check page."""
    if "html" not in ctype.lower():
        return False
    try:
        return extract(raw, url, 0, 2000)["total"] < 200
    except Exception:  # noqa: BLE001
        return False


async def read_html(url: str, browsers: tuple = (), before_browser=None, browser_only: bool = False) -> tuple[str, str, bytes, str]:
    """(final_url, content_type, body, how) through the tiers. browsers: the started-on-demand browser
    engines to try in order; a tier that returns a nearly empty HTML page counts as not good enough
    when a browser can still try. before_browser: awaited once, just before the first browser is used
    (the host's session handoff hangs here). browser_only: skip the request tier (a site known to need a browser)."""
    browsers = tuple(b for b in browsers if b is not None)
    thin = None
    try:
        if browser_only and browsers:
            raise BotWall("known to need a browser")
        try:
            final, ctype, raw = await asyncio.to_thread(fetch_impersonate, url)
            how = ""   # the ordinary way now; not worth a note
        except FetchError as exc:
            if "未安装" not in str(exc):
                raise
            final, ctype, raw = await asyncio.to_thread(fetch, url)
            how = ""
        if not (browsers and too_thin(ctype, raw, final)):
            return final, ctype, raw, how
        thin = (final, ctype, raw, how)
    except BotWall:
        pass
    if not browsers:
        raise BotWall("网站有反爬验证，且未启用浏览器")
    if before_browser is not None:
        await before_browser()
    why = []
    for b, how in zip(browsers, ("（经浏览器读取）", "（经第二浏览器读取）")):
        try:
            final, html, passed = await b.fetch_rendered(url)
        except PermissionError:
            raise
        except Exception as exc:  # noqa: BLE001 - this engine failed; the next may not
            log.info("browser tier (%s): %r", b.cfg.engine, exc)
            why.append(f"{b.cfg.engine} 出错 {type(exc).__name__}")
            continue
        if passed:
            return final, "text/html", html.encode("utf-8"), how
        why.append(f"{b.cfg.engine} {b.why}")
    if thin:
        return thin
    raise BotWall("网站的人机验证没有通过（" + "；".join(why) + "）")
