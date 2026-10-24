"""Local web page fetcher/extractor with SSRF protection.

Used by the astrbot_plugin_web_reader plugin. Kept free of AstrBot imports so
it can be unit-tested directly with any Python that has requests + bs4 + lxml.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

MAX_BYTES = 2_500_000
MAX_LINKS = 60
MAX_REDIRECTS = 5
DEFAULT_LIMIT = 6000
MAX_LIMIT = 12000
TIMEOUT = (5, 20)
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


class BlockedURL(Exception):
    """URL points to a non-public/forbidden target."""


class FetchError(Exception):
    """Fetching the page failed (network, HTTP, size)."""


def _is_public_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    if addr.version == 6 and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


def validate_url(url: str) -> str:
    """Reject non-http(s), credential URLs and hosts resolving to private IPs."""
    parts = urlsplit(url.strip())
    if parts.scheme not in {"http", "https"}:
        raise BlockedURL("只允许 http/https URL")
    if not parts.hostname:
        raise BlockedURL("URL 缺少主机名")
    if parts.username or parts.password:
        raise BlockedURL("URL 不允许携带账号/密码")
    host = parts.hostname
    try:
        if not _is_public_ip(str(ipaddress.ip_address(host))):
            raise BlockedURL("禁止访问本机/内网地址")
        return url
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(
            host,
            parts.port or (443 if parts.scheme == "https" else 80),
            proto=socket.IPPROTO_TCP,
        )
    except socket.gaierror as exc:
        raise FetchError(f"域名解析失败: {exc}") from exc
    for info in infos:
        ip = info[4][0]
        if not _is_public_ip(ip):
            raise BlockedURL(f"禁止访问内网地址（{host} -> {ip}）")
    return url


def fetch(url: str) -> tuple[str, str, bytes]:
    """Fetch URL with manual redirects, re-validating every hop."""
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        validate_url(current)
        try:
            resp = requests.get(
                current,
                headers={
                    "User-Agent": UA,
                    "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                },
                timeout=TIMEOUT,
                allow_redirects=False,
                stream=True,
            )
        except requests.RequestException as exc:
            raise FetchError(f"请求失败: {exc.__class__.__name__}") from exc

        if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get(
            "Location"
        ):
            current = urljoin(current, resp.headers["Location"])
            resp.close()
            continue
        if resp.status_code >= 400:
            code = resp.status_code
            resp.close()
            raise FetchError(f"HTTP {code}")
        ctype = resp.headers.get("Content-Type", "")
        raw = bytearray()
        try:
            for chunk in resp.iter_content(65536):
                raw.extend(chunk)
                if len(raw) > MAX_BYTES:
                    break
        finally:
            resp.close()
        return current, ctype, bytes(raw)
    raise FetchError("重定向次数过多")


def _clean_lines(text: str) -> str:
    lines = [re.sub(r"[ \t\u00a0]+", " ", ln).strip() for ln in text.splitlines()]
    return "\n".join(line for line in lines if line)


def extract(
    html: bytes, url: str, offset: int = 0, limit: int = DEFAULT_LIMIT
) -> dict:
    """Extract title, cleaned main text (chunked) and in-page links."""
    soup = BeautifulSoup(html, "lxml")
    title = ""
    if soup.title and soup.title.get_text(strip=True):
        title = " ".join(soup.title.get_text(" ", strip=True).split())
    elif soup.find("meta", property="og:title"):
        title = soup.find("meta", property="og:title").get("content", "")

    links: list[tuple[str, str]] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = urljoin(url, a["href"].strip())
        parts = urlsplit(href)
        if parts.scheme not in {"http", "https"}:
            continue
        if href.split("#")[0].rstrip("/") == url.split("#")[0].rstrip("/"):
            continue
        text = " ".join(a.get_text(" ", strip=True).split()) or (parts.path or href)
        key = href.split("#")[0]
        if key in seen:
            continue
        seen.add(key)
        links.append((text[:80], href))
        if len(links) >= MAX_LINKS:
            break

    for tag in soup(
        ["script", "style", "noscript", "iframe", "svg", "form", "nav", "header", "footer", "aside"]
    ):
        tag.decompose()
    main = soup.find("article") or soup.find("main")
    if main is None:
        main = soup.body or soup
    text = _clean_lines(main.get_text("\n"))
    total = len(text)
    offset = max(0, min(int(offset), total))
    limit = max(500, min(int(limit), MAX_LIMIT))
    end = min(total, offset + limit)
    return {
        "url": url,
        "title": title,
        "total": total,
        "start": offset,
        "end": end,
        "more": end < total,
        "text": text[offset:end],
        "links": links,
    }


def format_result(data: dict) -> str:
    head = [
        f"URL: {data['url']}",
        f"Title: {data['title']}",
        (
            f"Content: {data['total']} chars total, returned {data['start']}-{data['end']}"
            + (" (more available, call again with offset)" if data["more"] else " (complete)")
        ),
        "--- content ---",
        data["text"] or "(empty)",
        f"--- links ({len(data['links'])}) ---",
    ]
    body = [f"- {text} | {href}" for text, href in data["links"]]
    return "\n".join(head + body)
