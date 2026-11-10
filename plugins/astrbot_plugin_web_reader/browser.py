"""A real browser for the model: fetch tier for blocked pages, and page interaction.

Two uses, one browser (patchright, a Playwright fork with fewer automation tells), launched the
way patchright asks for: real Google Chrome when there is one, a visible window (on Linux
without a desktop the plugin starts its own Xvfb), no fixed viewport, no UA or header
overrides. Headless Chrome announces itself (HeadlessChrome in the UA and client hints), so it
is only the fallback when no display can be had.

1. Fetch tier. `fetch_rendered(url)` loads a page in the browser, waits out a Cloudflare-style
   challenge (clicking the Turnstile box when it shows one) and returns the rendered HTML,
   which `reader.extract` then turns into text + links like any other page. The profile
   directory is persistent, so a clearance cookie earned once is reused.
2. Interaction. `Session` keeps one tab per conversation: open, snapshot (accessibility tree
   with [ref=eN] handles), click, type, select, press, back. Enough to fill a questionnaire
   or play a small quiz page; no file access, no downloads, no JS evaluation exposed.

Every connection the browser makes goes through `GuardProxy`, a local forward proxy that
resolves the host itself and refuses private, loopback and link-local addresses, so a page
cannot steer the browser into the local network (and DNS rebinding has nothing to rebind:
the proxy connects to the address it checked). This replaces request interception, which
anti-bot scripts can notice.
A second engine, Camoufox (Firefox with the fingerprint set inside the engine), can serve as a
further fetch tier: sites that turn Chrome away sometimes let Firefox through and the reverse.
Its persona must be the host's own OS; a Windows persona on a Linux network stack fails checks
that the Linux persona passes.

Optional dependencies: without patchright `available()` is False and callers fall back to plain
fetching; without camoufox `available("camoufox")` is False and that tier is skipped.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import shutil
import socket
import sys
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

try:
    from patchright.async_api import async_playwright
except ImportError:  # pragma: no cover - optional
    async_playwright = None

log = logging.getLogger("astrbot")

CHALLENGE_MARKERS = ("Just a moment", "Performing security verification", "Attention Required",
                     "cf-chl", "challenge-platform", "Verify you are human", "DDoS-Guard",
                     "请稍候…", "正在进行安全验证", "确认您是真人", "安全验证 - 知乎", "百度安全验证",
                     "Please complete the additional verification challenge", "Security check required")
SNAPSHOT_CHARS = 9000
IDLE_SECONDS = 600


try:
    from camoufox.async_api import AsyncCamoufox
except ImportError:  # pragma: no cover - optional
    AsyncCamoufox = None

HOST_OS = {"linux": "linux", "win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")


def available(engine: str = "chrome") -> bool:
    return (AsyncCamoufox if engine == "camoufox" else async_playwright) is not None


def display_in_use(n: int, root: str = "/tmp") -> bool:
    """Is an X server answering on display :n? A socket or lock file alone proves nothing: a server
    that was killed leaves both behind."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.settimeout(1)
        s.connect(f"{root}/.X11-unix/X{n}")
        return True
    except OSError:
        return False
    finally:
        s.close()


def clear_display(n: int, root: str = "/tmp") -> None:
    for path in (f"{root}/.X11-unix/X{n}", f"{root}/.X{n}-lock"):
        try:
            os.unlink(path)
        except OSError:
            pass


def looks_blocked(status: int | None, text: str) -> bool:
    """A bot wall rather than the page: challenge markers, or 403/429/503 with a tiny body."""
    head = text[:20000]
    if any(m in head for m in CHALLENGE_MARKERS):
        return True
    return status in (403, 429, 503) and len(head) < 20000


def _public_ip(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if a.version == 6 and a.ipv4_mapped:
        a = a.ipv4_mapped
    return not (a.is_private or a.is_loopback or a.is_link_local or a.is_multicast or a.is_reserved or a.is_unspecified)


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
    ok = ok and all(_public_ip(ip) for ip in ips)
    _host_ok[host] = (ok, now)
    return ok


def request_allowed(url: str, allow_hosts: frozenset = frozenset()) -> bool:
    p = urlsplit(url)
    if p.scheme in ("data", "blob", "about"):
        return True
    if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password:
        return False
    return p.hostname in allow_hosts or _public_host(p.hostname)


class GuardProxy:
    """Forward proxy on 127.0.0.1 that the browser is pointed at. CONNECT and plain-HTTP requests
    are passed on only to public addresses; the proxy connects to the very address it checked."""

    DENY = b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
    FAIL = b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"

    def __init__(self, allow_hosts: frozenset = frozenset()):
        self.allow_hosts = allow_hosts
        self.port = 0
        self.denied = 0
        self._server = None

    async def start(self) -> int:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0, limit=1 << 20)
        self.port = self._server.sockets[0].getsockname()[1]
        return self.port

    async def close(self):
        if self._server is not None:
            self._server.close()
            self._server = None

    async def addresses(self, host: str, port: int) -> list[str]:
        """Addresses the proxy may connect to for this host; empty when the host is not allowed."""
        if host in self.allow_hosts:
            return [host]
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except (OSError, UnicodeError):
            return []
        ips = list(dict.fromkeys(i[4][0] for i in infos))
        return ips if ips and all(_public_ip(ip) for ip in ips) else []

    @staticmethod
    def parse(head: bytes) -> tuple[str, int, bytes] | None:
        """(host, port, bytes to send upstream first) from a proxy request head; None if malformed.
        CONNECT sends nothing first; a plain-HTTP request is rewritten to origin form."""
        try:
            line, rest = head.split(b"\r\n", 1)
            method, target, version = line.decode("latin-1").split(" ", 2)
            if method.upper() == "CONNECT":
                host, _, port = target.rpartition(":")
                return host.strip("[]"), int(port), b""
            p = urlsplit(target)
            if p.scheme != "http" or not p.hostname or p.username or p.password:
                return None
            path = (p.path or "/") + (f"?{p.query}" if p.query else "")
            drop = (b"proxy-connection:", b"connection:", b"proxy-authorization:")
            headers = [h for h in rest.split(b"\r\n") if h and not h.lower().startswith(drop)]
            first = f"{method} {path} {version}\r\n".encode("latin-1") + b"\r\n".join(headers + [b"Connection: close"]) + b"\r\n\r\n"
            return p.hostname, p.port or 80, first
        except (ValueError, UnicodeError):
            return None

    async def _handle(self, reader, writer):
        up = None
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 20)
            req = self.parse(head)
            ips = await self.addresses(req[0], req[1]) if req else []
            if not ips:
                self.denied += 1
                writer.write(self.DENY)
                await writer.drain()
                return
            host, port, first = req
            for ip in ips:
                try:
                    up_reader, up = await asyncio.wait_for(asyncio.open_connection(ip, port), 15)
                    break
                except (OSError, asyncio.TimeoutError):
                    up = None
            if up is None:
                writer.write(self.FAIL)
                await writer.drain()
                return
            if first:
                up.write(first)
            else:
                writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
            await asyncio.gather(self._pipe(reader, up), self._pipe(up_reader, writer))
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError, OSError):
            pass
        finally:
            for w in (writer, up):
                if w is not None:
                    try:
                        w.close()
                    except Exception:  # noqa: BLE001
                        pass

    @staticmethod
    async def _pipe(src, dst):
        try:
            while data := await src.read(65536):
                dst.write(data)
                await dst.drain()
        except (OSError, asyncio.CancelledError):
            pass
        finally:
            try:
                dst.close()
            except Exception:  # noqa: BLE001
                pass


@dataclass
class BrowserConfig:
    profile_dir: str
    engine: str = "chrome"         # "chrome" (patchright) or "camoufox" (fetch tier only)
    executable_path: str = ""      # empty: system Google Chrome if present, else patchright's Chromium
    headless: bool = False         # False: visible window (own Xvfb on a Linux box without a desktop)
    locale: str = "zh-CN"
    timezone: str = ""             # e.g. Asia/Shanghai; empty keeps the system zone. Should match the egress IP.
    xvfb_command: str = "Xvfb"
    challenge_wait: float = 45.0
    min_host_interval: float = 3.0  # seconds between page loads on one host; fast loading trips rate checks
    allow_hosts: frozenset = frozenset()  # tests only (local fixture server)


class Browser:
    """One persistent browser context shared by the fetch tier and all sessions."""

    def __init__(self, cfg: BrowserConfig):
        self.cfg = cfg
        self._pw = None
        self._ctx = None
        self._lock = asyncio.Lock()
        self.proxy = GuardProxy(cfg.allow_hosts)
        self._xvfb = None
        self._display_no = -1
        self._fox = None
        self._last_nav: dict[str, float] = {}
        self._front_door: set[str] = set()  # hosts that refuse a cold deep link but serve it from inside the site
        self.mode = ""  # how the browser ended up running: "headed", "xvfb" or "headless"

    async def _display(self, env: dict) -> bool:
        """Make sure a visible window has somewhere to go. True when headed mode can be used."""
        if not sys.platform.startswith("linux") or env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"):
            self.mode = "headed"
            return True
        cmd = self.cfg.xvfb_command or "Xvfb"
        if not (shutil.which(cmd) or os.path.isfile(cmd)):
            log.warning("web_reader: no display and no Xvfb (%s); the browser will run headless, "
                        "which sites detect more easily", cmd)
            return False
        for n in range(90, 110):
            if display_in_use(n):
                continue
            clear_display(n)  # leftovers of a server that was killed would make the number look taken
            proc = await asyncio.create_subprocess_exec(
                cmd, f":{n}", "-screen", "0", "1920x1080x24", "-nolisten", "tcp",
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            for _ in range(50):
                if display_in_use(n):
                    self._xvfb, self._display_no, env["DISPLAY"], self.mode = proc, n, f":{n}", "xvfb"
                    return True
                if proc.returncode is not None:
                    break
                await asyncio.sleep(0.1)
            if proc.returncode is None:
                proc.kill()
        log.warning("web_reader: Xvfb did not start; the browser will run headless, which sites detect more easily")
        return False

    def _targets(self) -> list[dict]:
        """Browsers to try, best first: the configured binary, or system Google Chrome (what sites
        expect; Chromium builds differ in codecs and brands) and then patchright's own Chromium."""
        if self.cfg.executable_path:
            return [{"executable_path": self.cfg.executable_path}]
        return [{"channel": "chrome"}, {}]

    async def _headless_ua(self) -> str:
        """Headless Chrome's UA with the word Headless taken out (version and platform stay real)."""
        for target in self._targets():
            try:
                b = await self._pw.chromium.launch(headless=True, **target)
            except Exception:  # noqa: BLE001 - this browser is not installed
                continue
            try:
                page = await b.new_page()
                return (await page.evaluate("navigator.userAgent")).replace("HeadlessChrome", "Chrome")
            finally:
                await b.close()
        return ""

    def _webrtc_through_proxy(self) -> None:
        """WebRTC sends UDP straight out, past the proxy and its address check. The profile preference
        (the command-line switch is ignored by current Chrome) keeps it to what the proxy carries."""
        path = os.path.join(self.cfg.profile_dir, "Default", "Preferences")
        try:
            with open(path, encoding="utf-8") as f:
                prefs = json.load(f)
        except (OSError, ValueError):
            prefs = {}
        if prefs.get("webrtc", {}).get("ip_handling_policy") == "disable_non_proxied_udp":
            return
        prefs.setdefault("webrtc", {})["ip_handling_policy"] = "disable_non_proxied_udp"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(prefs, f)

    async def _launch(self, kw: dict):
        err = None
        for target in self._targets():
            try:
                return await self._pw.chromium.launch_persistent_context(**target, **kw)
            except Exception as exc:  # noqa: BLE001 - try the next browser
                err = exc
        raise err

    async def context(self):
        async with self._lock:
            if self._ctx is None:
                fox = self.cfg.engine == "camoufox"
                if not available(self.cfg.engine):
                    raise RuntimeError(f"{'camoufox' if fox else 'patchright'} is not installed")
                await self.proxy.start()
                env = dict(os.environ)
                if self.cfg.timezone:
                    env["TZ"] = self.cfg.timezone
                headless = self.cfg.headless or not await self._display(env)
                proxy = {"server": f"http://127.0.0.1:{self.proxy.port}"}
                if fox:
                    self.mode = "headless" if headless else self.mode
                    # Firefox keeps loopback off the proxy unless told otherwise; the guard must see everything
                    prefs = {"network.proxy.allow_hijacking_localhost": True, "network.proxy.no_proxies_on": ""}
                    self._fox = AsyncCamoufox(headless=headless, env=env, os=HOST_OS, locale=self.cfg.locale, proxy=proxy,
                                              persistent_context=True, user_data_dir=self.cfg.profile_dir,
                                              firefox_user_prefs=prefs)
                    self._ctx = await self._fox.__aenter__()
                    return self._ctx
                self._pw = await async_playwright().start()
                lang = self.cfg.locale
                args = [f"--lang={lang}", f"--accept-lang={lang},{lang.split('-')[0]},en", "--window-size=1600,950"]
                self._webrtc_through_proxy()
                kw = dict(user_data_dir=self.cfg.profile_dir, headless=headless, no_viewport=True, accept_downloads=False,
                          env=env, args=args, proxy=proxy)
                if headless:
                    self.mode = "headless"
                    ua = await self._headless_ua()
                    if ua:
                        args.append(f"--user-agent={ua}")
                self._ctx = await self._launch(kw)
                self._ctx.on("page", lambda p: p.on("dialog", lambda d: asyncio.ensure_future(d.dismiss())))
            return self._ctx

    async def pace(self, url: str) -> None:
        """Keep page loads on one host at least `min_host_interval` apart."""
        host = urlsplit(url).hostname or ""
        now = time.time()
        wait = self._last_nav.get(host, 0) + self.cfg.min_host_interval - now
        self._last_nav[host] = now + max(wait, 0)
        if wait > 0:
            await asyncio.sleep(wait)

    async def close(self):
        if self._fox is not None:
            await self._fox.__aexit__(None, None, None)
        elif self._ctx is not None:
            await self._ctx.close()
            await self._pw.stop()
        self._ctx = self._pw = self._fox = None
        await self.proxy.close()
        if self._xvfb is not None:
            if self._xvfb.returncode is None:
                self._xvfb.terminate()
                try:
                    await asyncio.wait_for(self._xvfb.wait(), 5)
                except asyncio.TimeoutError:
                    self._xvfb.kill()
            for _ in range(20):  # a wrapper script may exit a moment before the server itself
                if not display_in_use(self._display_no):
                    clear_display(self._display_no)
                    break
                await asyncio.sleep(0.1)
        self._xvfb = None

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

    async def _navigate(self, page, url: str, from_page: bool = False, referer: str = "") -> int:
        """One page load: typed into the address bar (optionally naming a Referer), or (`from_page`)
        started by the page that is showing. Returns the HTTP status (0 when there was no response
        to speak of, e.g. a same-document navigation; 503 for an error answer with no body)."""
        await self.pace(url)
        try:
            if from_page:
                async with page.expect_navigation(timeout=40000, wait_until="domcontentloaded") as nav:
                    await page.evaluate("u => { location.assign(u) }", url)
                resp = await nav.value
            else:
                resp = await page.goto(url, timeout=40000, wait_until="domcontentloaded",
                                       **({"referer": referer} if referer else {}))
            return resp.status if resp else 0
        except Exception as exc:  # noqa: BLE001
            if "ERR_HTTP_RESPONSE_CODE_FAILURE" in str(exc):
                return 503
            raise

    async def _refused(self, page, status: int) -> bool:
        """Turned away outright: an error answer and no challenge on the page to wait for or solve."""
        try:
            uri = await page.evaluate("document.documentURI")
        except Exception:  # noqa: BLE001 - mid-navigation
            uri = page.url
        if uri.startswith(("chrome-error:", "about:neterror")):  # the browser's own "can't show this" page
            return True
        if status not in (403, 429, 503):
            return False
        try:
            seen = await page.title() + (await page.inner_text("body", timeout=3000))[:3000]
        except Exception:  # noqa: BLE001
            return False
        return not any(m in seen for m in CHALLENGE_MARKERS)

    async def _arrive(self, page, url: str, **how) -> str:
        """Navigate and see it through: "ok" (the page is showing), "refused" (an error answer with
        nothing to solve) or "challenge" (a bot check that did not clear in time)."""
        last = {"status": 0}

        def note(resp):  # a passed challenge reloads the page; the answer that counts is the last one
            try:
                if resp.request.is_navigation_request() and resp.frame == page.main_frame:
                    last["status"] = resp.status
            except Exception:  # noqa: BLE001
                pass

        page.on("response", note)
        try:
            status = await self._navigate(page, url, **how)
            last["status"] = last["status"] or status
            if await self._refused(page, last["status"]):
                return "refused"
            if not await self.pass_challenge(page):
                return "challenge"
            return "refused" if await self._refused(page, last["status"]) else "ok"
        finally:
            page.remove_listener("response", note)

    async def load(self, page, url: str) -> bool:
        """Load `url` in `page`; True when the page itself, not a bot check, is showing.

        Some sites answer a deep link opened cold (no Referer) with a bare error and serve the same
        page to a visitor who arrives from inside the site; rateyourmusic's release pages do. A
        refusal with no challenge to solve is therefore retried through the front door: the
        site's home page first, then a navigation from that page to the target. The host is
        remembered, and later loads there name the home page as Referer from the start."""
        p = urlsplit(url)
        host, home = p.hostname or "", f"{p.scheme}://{p.netloc}/"
        state = await self._arrive(page, url, referer=home if host in self._front_door else "")
        if state != "refused" or (p.path in ("", "/") and not p.query):
            return state == "ok"
        if await self._arrive(page, home) != "ok":
            return False
        await page.mouse.move(420, 310, steps=8)
        if await self._arrive(page, url, from_page=True) != "ok":
            return False
        self._front_door.add(host)
        return True

    async def fetch_rendered(self, url: str, settle_ms: int = 1500) -> tuple[str, str, bool]:
        """(final_url, html, passed) for a page loaded in the browser."""
        if not request_allowed(url, self.cfg.allow_hosts):
            raise PermissionError("禁止访问本机/内网地址")
        page = await self.new_page()
        try:
            passed = await self.load(page, url)
            try:
                await page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:  # noqa: BLE001 - busy pages never go idle
                pass
            await page.wait_for_timeout(settle_ms)
            if passed:  # some sites load the page first and only then redirect to their check
                passed = await self.pass_challenge(page)
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
            passed = await self.browser.load(page, url)
        except Exception as exc:  # noqa: BLE001
            return f"错误：打开失败（{str(exc).splitlines()[0][:120]}）"
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
