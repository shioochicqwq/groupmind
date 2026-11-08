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
