"""Unit tests for the astrbot_plugin_web_reader link extraction (plugin is not on sys.path)."""

import importlib.util
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "astrbot_plugin_web_reader" / "reader.py"


def _reader():
    spec = importlib.util.spec_from_file_location("web_reader_plugin_reader", PLUGIN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _html(nav: int, body: int, tail: int = 0) -> bytes:
    nav_links = "".join(f'<a href="/nav{i}">nav{i}</a>' for i in range(nav))
    body_links = "".join(f'<a href="/doc{i}">doc{i}</a>' for i in range(body))
    tail_links = "".join(f'<a href="/tail{i}">tail{i}</a>' for i in range(tail))
    return (
        f"<html><head><title>t</title></head><body>"
        f"<nav>{nav_links}</nav>"
        f"<article><p>main text</p>{body_links}</article>"
        f"<div>{tail_links}</div>"
        f"</body></html>"
    ).encode()


def test_content_links_come_before_navigation_links():
    r = _reader()
    d = r.extract(_html(nav=60, body=2), "https://example.com/")
    hrefs = [href for _text, href in d["links"]]
    assert hrefs[:2] == ["https://example.com/doc0", "https://example.com/doc1"]
    assert "https://example.com/nav0" in hrefs


def test_links_are_paginated_and_report_more():
    r = _reader()
    d = r.extract(_html(nav=0, body=0, tail=180), "https://example.com/")
    assert d["links_total"] == 180
    assert len(d["links"]) == r.MAX_LINKS
    assert d["links_more"] is True
    assert d["links_next"] == r.MAX_LINKS
    rest = r.extract(_html(nav=0, body=0, tail=180), "https://example.com/", links_offset=d["links_next"])
    assert len(rest["links"]) == 180 - r.MAX_LINKS
    assert rest["links_more"] is False


def test_links_limit_none_returns_everything():
    r = _reader()
    d = r.extract(_html(nav=3, body=0, tail=170), "https://example.com/", links_limit=None)
    assert d["links_total"] == 173
    assert len(d["links"]) == 173


def test_same_page_and_duplicate_links_are_dropped():
    r = _reader()
    html = (
        '<html><body><a href="https://example.com/">self</a>'
        '<a href="https://example.com/a#x">a1</a>'
        '<a href="https://example.com/a#y">a2</a>'
        '<a href="mailto:x@example.com">mail</a>'
        '<a href="https://other.example/b">b</a></body></html>'
    ).encode()
    d = r.extract(html, "https://example.com/")
    assert [href for _text, href in d["links"]] == ["https://example.com/a#x", "https://other.example/b"]


def test_format_result_mentions_links_more():
    r = _reader()
    d = r.extract(_html(nav=0, body=0, tail=200), "https://example.com/")
    text = r.format_result(d)
    assert "links_offset=" in text


def test_bot_wall_detection():
    r = _reader()
    assert r.is_wall(403, b"<title>Just a moment...</title>")
    assert r.is_wall(200, b"<html>Performing security verification</html>")
    assert r.is_wall(429, b"")
    assert not r.is_wall(200, b"<html><title>ok</title><p>hello</p></html>")


def _browser():
    import sys
    spec = importlib.util.spec_from_file_location("web_reader_plugin_browser", PLUGIN.with_name("browser.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look the module up
    spec.loader.exec_module(module)
    return module


def test_browser_requests_stay_public():
    b = _browser()
    assert not b.request_allowed("http://127.0.0.1:8317/v1/models")
    assert not b.request_allowed("http://10.0.0.5/")
    assert not b.request_allowed("http://[::1]/")
    assert not b.request_allowed("file:///etc/passwd")
    assert not b.request_allowed("https://user:pw@example.com/")
    assert b.request_allowed("data:text/plain,hi")
    assert b.request_allowed("http://127.0.0.1:9/", frozenset({"127.0.0.1"}))  # test fixture escape hatch only


def test_guard_proxy_parses_requests():
    g = _browser().GuardProxy
    assert g.parse(b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n") == ("example.com", 443, b"")
    assert g.parse(b"CONNECT [::1]:443 HTTP/1.1\r\n\r\n")[0] == "::1"
    host, port, first = g.parse(b"GET http://example.com:8080/a?b=1 HTTP/1.1\r\nHost: example.com:8080\r\n"
                                b"Proxy-Connection: keep-alive\r\nProxy-Authorization: x\r\n\r\n")
    assert (host, port) == ("example.com", 8080)
    assert first.startswith(b"GET /a?b=1 HTTP/1.1\r\nHost: example.com:8080\r\n")
    assert b"Proxy-" not in first and first.endswith(b"Connection: close\r\n\r\n")
    assert g.parse(b"GET ftp://example.com/ HTTP/1.1\r\n\r\n") is None
    assert g.parse(b"GET http://user:pw@example.com/ HTTP/1.1\r\n\r\n") is None
    assert g.parse(b"garbage\r\n\r\n") is None


def test_guard_proxy_refuses_local_destinations():
    """The browser's only way out is this proxy: loopback, private and metadata addresses get 403
    and the local server never sees a connection; an allow-listed host (tests only) is relayed."""
    import asyncio
    import http.server
    import threading

    b = _browser()
    hits = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(200)
            self.send_header("Content-Length", "6")
            self.end_headers()
            self.wfile.write(b"secret")

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_port

    async def ask(proxy_port, head: bytes, whole: bool = False) -> bytes:
        reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
        writer.write(head)
        await writer.drain()
        # whole: until the far end closes (headers and body can arrive in separate pieces)
        data = await asyncio.wait_for(reader.read(-1 if whole else 4096), 10)
        writer.close()
        return data

    async def run():
        closed = b.GuardProxy()
        await closed.start()
        for head in (f"GET http://127.0.0.1:{port}/x HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n",
                     f"CONNECT 127.0.0.1:{port} HTTP/1.1\r\n\r\n",
                     f"CONNECT localhost:{port} HTTP/1.1\r\n\r\n",
                     "CONNECT 10.0.0.5:80 HTTP/1.1\r\n\r\n",
                     "CONNECT 169.254.169.254:80 HTTP/1.1\r\n\r\n",
                     f"CONNECT [::ffff:127.0.0.1]:{port} HTTP/1.1\r\n\r\n"):
            assert (await ask(closed.port, head.encode())).startswith(b"HTTP/1.1 403"), head
        assert closed.denied == 6 and hits == []
        await closed.close()

        opened = b.GuardProxy(frozenset({"127.0.0.1"}))
        await opened.start()
        plain = await ask(opened.port, f"GET http://127.0.0.1:{port}/ok HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n\r\n".encode(), whole=True)
        assert plain.startswith(b"HTTP/1.0 200") and plain.endswith(b"secret")
        assert (await ask(opened.port, f"CONNECT 127.0.0.1:{port} HTTP/1.1\r\n\r\n".encode())).startswith(b"HTTP/1.1 200")
        await opened.close()

    try:
        asyncio.run(run())
    finally:
        srv.shutdown()
    assert hits == ["/ok"]


class _Resp:
    def __init__(self, status):
        self.status = status


class _Nav:
    def __init__(self, page):
        self.page = page

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    @property
    def value(self):
        async def get():
            return self.page.last
        return get()


class _FakeSite:
    """A site whose /deep page answers 503 with no body unless the request names a Referer."""

    def __init__(self):
        self.log, self.url, self.last = [], "", None
        self.mouse = self

    async def move(self, *a, **k):
        pass

    def on(self, *a):
        pass

    remove_listener = on

    def _serve(self, url, referer):
        self.log.append((url, referer))
        if url.endswith("/deep") and not referer:
            raise RuntimeError("Page.goto: net::ERR_HTTP_RESPONSE_CODE_FAILURE at " + url)
        self.url, self.last = url, _Resp(200)
        return self.last

    async def goto(self, url, referer="", **k):
        return self._serve(url, referer)

    def expect_navigation(self, **k):
        return _Nav(self)

    async def evaluate(self, js, url=None):
        if url is None:  # document.documentURI
            return self.url
        self._serve(url, self.url)

    async def title(self):
        return "page"

    async def inner_text(self, sel, **k):
        return "real text"


def test_cold_deep_link_refusal_is_retried_through_the_home_page():
    import asyncio
    br = _browser()
    b = br.Browser(br.BrowserConfig(profile_dir="unused", min_host_interval=0))
    page = _FakeSite()
    assert asyncio.run(b.load(page, "https://site.example/deep")) is True
    assert page.log == [("https://site.example/deep", ""), ("https://site.example/", ""),
                        ("https://site.example/deep", "https://site.example/")]
    # the host is remembered: the next deep link names the home page as Referer at once
    page.log.clear()
    assert asyncio.run(b.load(page, "https://site.example/deep")) is True
    assert page.log == [("https://site.example/deep", "https://site.example/")]


def test_refused_home_page_is_not_retried():
    import asyncio
    br = _browser()

    class Down(_FakeSite):
        def _serve(self, url, referer):
            self.log.append((url, referer))
            raise RuntimeError("net::ERR_HTTP_RESPONSE_CODE_FAILURE")
    b = br.Browser(br.BrowserConfig(profile_dir="unused", min_host_interval=0))
    page = Down()
    assert asyncio.run(b.load(page, "https://site.example/")) is False
    assert len(page.log) == 1
    assert asyncio.run(b.load(page, "https://site.example/deep")) is False
    assert len(page.log) == 3 and not b._front_door
