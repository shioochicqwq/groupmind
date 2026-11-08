"""A real browser for the model: fetch tier for blocked pages, and page interaction.

Two uses, one browser (patchright, a Playwright fork with fewer automation tells):

1. Fetch tier. `fetch_rendered(url)` loads a page in the browser, waits out a Cloudflare-style
   challenge (clicking the Turnstile box when it shows one) and returns the rendered HTML,
   which `reader.extract` then turns into text + links like any other page. The profile
   directory is persistent, so a clearance cookie earned once is reused.
2. Interaction. `Session` keeps one tab per conversation: open, snapshot (accessibility tree
   with [ref=eN] handles), click, type, select, press, back. Enough to fill a questionnaire
   or play a small quiz page; no file access, no downloads, no JS evaluation exposed.

Every request the browser makes (page, frame, script, XHR) goes through the same public-
address check as the plain fetcher, so a page cannot steer it into the local network.
Optional dependency: if patchright is not installed, `available()` is False and callers fall
back to plain fetching.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

try:
    from patchright.async_api import async_playwright
except ImportError:  # pragma: no cover - optional
    async_playwright = None

CHALLENGE_MARKERS = ("Just a moment", "Performing security verification", "Attention Required",
                     "cf-chl", "challenge-platform", "Verify you are human", "DDoS-Guard",
                     "请稍候…", "正在进行安全验证", "确认您是真人", "安全验证 - 知乎", "百度安全验证")
SNAPSHOT_CHARS = 9000
IDLE_SECONDS = 600


def available() -> bool:
    return async_playwright is not None


def looks_blocked(status: int | None, text: str) -> bool:
    """A bot wall rather than the page: challenge markers, or 403/429/503 with a tiny body."""
    head = text[:20000]
    if any(m in head for m in CHALLENGE_MARKERS):
        return True
    return status in (403, 429, 503) and len(head) < 20000


_host_ok: dict[str, tuple[bool, float]] = {}


def _public_host(host: str) -> bool:
    now = time.time()
    hit = _host_ok.get(host)
    if hit and now - hit[1] < 300:
        return hit[0]
    ok = True
    try:
        ips = [str(ipaddress.ip_address(host))]
    except ValueError:
        try:
            ips = [i[4][0] for i in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)]
        except socket.gaierror:
            ips, ok = [], False
    for ip in ips:
        a = ipaddress.ip_address(ip)
        if a.version == 6 and a.ipv4_mapped:
            a = a.ipv4_mapped
        if a.is_private or a.is_loopback or a.is_link_local or a.is_multicast or a.is_reserved or a.is_unspecified:
            ok = False
    _host_ok[host] = (ok, now)
    return ok


def request_allowed(url: str, allow_hosts: frozenset = frozenset()) -> bool:
    p = urlsplit(url)
    if p.scheme in ("data", "blob", "about"):
        return True
    if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password:
        return False
    return p.hostname in allow_hosts or _public_host(p.hostname)


@dataclass
class BrowserConfig:
    profile_dir: str
    executable_path: str = ""
    headless: bool = True
    locale: str = "zh-CN"
    challenge_wait: float = 45.0
    allow_hosts: frozenset = frozenset()  # tests only (local fixture server)


class Browser:
    """One persistent browser context shared by the fetch tier and all sessions."""

    def __init__(self, cfg: BrowserConfig):
        self.cfg = cfg
        self._pw = None
        self._ctx = None
        self._lock = asyncio.Lock()

    async def context(self):
        async with self._lock:
            if self._ctx is None:
                if not available():
                    raise RuntimeError("patchright is not installed")
                self._pw = await async_playwright().start()
                kw = dict(user_data_dir=self.cfg.profile_dir, headless=self.cfg.headless, locale=self.cfg.locale,
                          viewport={"width": 1366, "height": 850}, accept_downloads=False)
                if self.cfg.executable_path:
                    kw["executable_path"] = self.cfg.executable_path
                self._ctx = await self._pw.chromium.launch_persistent_context(**kw)
                await self._ctx.route("**/*", self._guard)
                self._ctx.on("page", lambda p: p.on("dialog", lambda d: asyncio.ensure_future(d.dismiss())))
            return self._ctx

    async def _guard(self, route):
        if request_allowed(route.request.url, self.cfg.allow_hosts):
            await route.continue_()
        else:
            await route.abort("blockedbyclient")

    async def close(self):
        if self._ctx is not None:
            await self._ctx.close()
            await self._pw.stop()
            self._ctx = self._pw = None

    async def new_page(self):
        ctx = await self.context()
        page = await ctx.new_page()
        page.on("dialog", lambda d: asyncio.ensure_future(d.dismiss()))
        return page

    async def pass_challenge(self, page) -> bool:
        """Wait for a bot-check page to clear; click a Turnstile box if one is shown."""
        t0, clicks = time.time(), 0
        while time.time() - t0 < self.cfg.challenge_wait:
            try:
                title = await page.title()
                body = await page.inner_text("body", timeout=3000)
            except Exception:  # noqa: BLE001 - navigation in progress
                await page.wait_for_timeout(1000)
                continue
            if not any(m in title or m in body[:3000] for m in CHALLENGE_MARKERS):
                return True
            box = None
            for f in page.frames:
                if "challenges.cloudflare.com" in f.url:
                    try:
                        box = await (await f.frame_element()).bounding_box()
                    except Exception:  # noqa: BLE001
                        box = None
            if box and box["width"] > 50 and clicks < 3:
                await page.mouse.move(box["x"] + 10, box["y"] + 5, steps=8)
                await page.mouse.click(box["x"] + 22, box["y"] + box["height"] / 2)
                clicks += 1
                await page.wait_for_timeout(5000)
            else:
                await page.wait_for_timeout(2000)
        return False

    async def fetch_rendered(self, url: str, settle_ms: int = 1500) -> tuple[str, str, bool]:
        """(final_url, html, passed) for a page loaded in the browser."""
        if not request_allowed(url, self.cfg.allow_hosts):
            raise PermissionError("禁止访问本机/内网地址")
        page = await self.new_page()
        try:
            await page.goto(url, timeout=40000, wait_until="domcontentloaded")
            passed = await self.pass_challenge(page)
            try:
                await page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:  # noqa: BLE001 - busy pages never go idle
                pass
            await page.wait_for_timeout(settle_ms)
            return page.url, await page.content(), passed
        finally:
            await page.close()


@dataclass
class Session:
    """One tab the model drives. Every action returns a fresh snapshot."""
    browser: Browser
    page: object = None
    last_used: float = field(default_factory=time.time)

    async def _page(self):
        if self.page is None or self.page.is_closed():
            self.page = await self.browser.new_page()
        self.last_used = time.time()
        return self.page

    async def _tree(self) -> str:
        page = await self._page()
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=8000)
        except Exception:  # noqa: BLE001
            pass
        await page.wait_for_timeout(400)
        return await page.aria_snapshot(mode="ai")

    async def snapshot(self, note: str = "", offset: int = 0) -> str:
        page = await self._page()
        tree = await self._tree()
        total = len(tree)
        offset = max(0, min(int(offset or 0), total))
        if offset:  # start on a line boundary
            offset = tree.rfind("\n", 0, offset) + 1
        part = tree[offset:offset + SNAPSHOT_CHARS]
        if offset + SNAPSHOT_CHARS < total:
            part = part[:part.rfind("\n") + 1] or part
        end = offset + len(part)
        more = ""
        if offset or end < total:
            more = (f"\n…（页面结构共 {total} 字，这里是 {offset}-{end}"
                    + (f"；看后面用 browser_key action=snapshot key={end}" if end < total else "")
                    + "；找特定内容用 browser_find）")
        head = f"{note}\n" if note else ""
        return f"{head}页面：{await page.title()}\nURL：{page.url}\n\n{part}{more}"

    async def find(self, query: str, context: int = 2, max_hits: int = 8) -> str:
        """Lines of the page structure containing `query` (case-insensitive), with a little context."""
        page = await self._page()
        lines = (await self._tree()).splitlines()
        q = (query or "").strip().lower()
        if not q:
            return "错误：查找内容为空"
        hits = [i for i, line in enumerate(lines) if q in line.lower()]
        if not hits:
            return f"页面：{await page.title()}\n没有找到「{query}」（页面结构共 {len(lines)} 行）。可换个说法，或内容需要先点击/展开才出现。"
        out = []
        for i in hits[:max_hits]:
            lo, hi = max(0, i - context), min(len(lines), i + context + 1)
            out.append("\n".join(lines[lo:hi]))
        extra = f"\n…还有 {len(hits) - max_hits} 处匹配" if len(hits) > max_hits else ""
        return f"页面：{await page.title()}\n找到 {len(hits)} 处「{query}」：\n\n" + "\n---\n".join(out) + extra

    async def open(self, url: str) -> str:
        if not request_allowed(url, self.browser.cfg.allow_hosts):
            return "错误：只允许公开的 http/https 地址"
        page = await self._page()
        try:
            await page.goto(url, timeout=40000, wait_until="domcontentloaded")
        except Exception as exc:  # noqa: BLE001
            return f"错误：打开失败（{str(exc).splitlines()[0][:120]}）"
        passed = await self.browser.pass_challenge(page)
        return await self.snapshot("" if passed else "（注意：页面可能仍停在人机验证，没能通过）")

    def _loc(self, ref: str):
        ref = ref.strip().strip("[]").replace("ref=", "")
        return self.page.locator(f"aria-ref={ref}")

    async def _click(self, loc) -> None:
        """Click the deepest clickable element inside the target. Accessibility snapshots often
        collapse a small div button into its full-width wrapper, whose centre is empty space."""
        handle = await loc.element_handle(timeout=8000)
        inner = await handle.evaluate_handle("""el => {
            const visible = n => { const r = n.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
            const handler = n => !!(n.onclick || n.hasAttribute('onclick') || n.getAttribute('role') === 'button'
                || ['A', 'BUTTON', 'INPUT', 'LABEL', 'SELECT', 'SUMMARY', 'TEXTAREA'].includes(n.tagName));
            if (handler(el)) return el;
            const inside = [...el.querySelectorAll('*')].filter(n => visible(n) && handler(n));
            if (inside.length === 1) return inside[0];
            if (inside.length > 1) return el;  // several controls: the ref was too coarse, keep the model's choice
            // no explicit handler: the element where cursor:pointer starts (listeners added elsewhere)
            const ptr = [...el.querySelectorAll('*')].filter(n => visible(n) && getComputedStyle(n).cursor === 'pointer'
                && getComputedStyle(n.parentElement).cursor !== 'pointer');
            return ptr.length === 1 ? ptr[0] : el;
        }""")
        target = inner.as_element() or handle
        await target.scroll_into_view_if_needed(timeout=5000)
        await target.click(timeout=8000)

    async def act(self, action: str, ref: str = "", text: str = "", submit: bool = False) -> str:
        page = await self._page()
        if page.url in ("", "about:blank"):
            return "错误：还没有打开页面，先用 browser_open"
        try:
            if action == "click":
                await self._click(self._loc(ref))
            elif action == "type":
                loc = self._loc(ref)
                await loc.fill(text, timeout=8000)
                if submit:
                    await loc.press("Enter")
            elif action == "select":
                await self._loc(ref).select_option([v.strip() for v in text.split("|") if v.strip()], timeout=8000)
            elif action == "press":
                await page.keyboard.press(text or "Enter")
            elif action == "back":
                await page.go_back(timeout=15000)
            else:
                return f"错误：不支持的操作 {action}"
        except Exception as exc:  # noqa: BLE001
            return await self.snapshot(f"操作失败：{str(exc).splitlines()[0][:160]}（ref 可能已变，按下面的新快照重试）")
        await page.wait_for_timeout(600)
        return await self.snapshot(f"已执行 {action} {ref}".strip())

    async def close(self):
        if self.page is not None and not self.page.is_closed():
            await self.page.close()
        self.page = None
