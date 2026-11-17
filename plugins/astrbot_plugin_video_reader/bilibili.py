"""What a Bilibili video page says in text: title, uploader, numbers, description, tags, parts, subtitles when the
site gives them without a login, and the most liked comments. Public endpoints, no login, no cookies.

This goes with watching the video: the comments and the description are not in the picture, and when the
download is refused (data-centre addresses get HTTP 412) the text is still there. The endpoints are the ones
Bilibili-Video-Research (MIT) uses; a browser-like User-Agent without cookies is what gets refused, so a plain one is sent.
"""
from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

API, UA = "https://api.bilibili.com", "qqbot-video-reader/0.1"
HOSTS = ("bilibili.com", "b23.tv")
BVID = re.compile(r"BV[0-9A-Za-z]{10}")
COMMENTS, COMMENT_CHARS, SUBTITLE_CHARS = 8, 300, 6000


def is_ours(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in HOSTS)


def _open(url: str, timeout: float = 15):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=timeout)


def _json(url: str) -> dict:
    with _open(url) as r:
        return json.load(r)


def bvid(url: str) -> str:
    """The video id in the link; a short link is followed to where it leads."""
    m = BVID.search(url)
    if not m and (urlsplit(url).hostname or "").lower().endswith("b23.tv"):
        with _open(url) as r:
            m = BVID.search(r.geturl())
    return m.group(0) if m else ""


def _clock(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    return f"{m:02d}:{s:02d}"


def page_text(url: str) -> str:
    """Empty when the link is not a Bilibili video or the site gives nothing."""
    try:
        bv = bvid(url)
        d = _json(f"{API}/x/web-interface/view?bvid={bv}").get("data") if bv else None
    except (OSError, ValueError):
        return ""
    if not d:
        return ""
    st, day = d.get("stat") or {}, datetime.fromtimestamp(d.get("pubdate", 0), timezone(timedelta(hours=8)))
    out = [f"标题：{d.get('title', '')}", f"UP 主：{(d.get('owner') or {}).get('name', '')}；发布 {day:%Y-%m-%d}；时长 {_clock(d.get('duration', 0))}",
           f"播放 {st.get('view', '?')}，弹幕 {st.get('danmaku', '?')}，评论 {st.get('reply', '?')}，点赞 {st.get('like', '?')}，投币 {st.get('coin', '?')}，收藏 {st.get('favorite', '?')}"]
    if (d.get("desc") or "").strip():
        out.append(f"简介：{d['desc'].strip()[:800]}")
    pages = d.get("pages") or []
    if len(pages) > 1:
        out.append(f"分 P（{len(pages)} 个）：" + "；".join(f"P{p.get('page')} {p.get('part', '')}" for p in pages[:30]))

    def part(what: str, fn) -> None:   # each is extra: one failing leaves the rest
        try:
            got = fn()
        except (OSError, ValueError, KeyError, TypeError):
            got = ""
        if got:
            out.append(f"{what}：{got}")

    part("标签", lambda: "、".join(t["tag_name"] for t in _json(f"{API}/x/tag/archive/tags?bvid={bv}").get("data") or []))

    def subtitles() -> str:
        subs = ((_json(f"{API}/x/player/v2?aid={d['aid']}&cid={d['cid']}").get("data") or {}).get("subtitle") or {}).get("subtitles") or []
        if not subs:
            return ""
        link = subs[0]["subtitle_url"]
        body = _json("https:" + link if link.startswith("//") else link).get("body") or []
        return ("\n" + "\n".join(f"[{_clock(c.get('from', 0))}] {c.get('content', '').strip()}" for c in body))[:SUBTITLE_CHARS]

    part("字幕", subtitles)

    def comments() -> str:
        data = _json(f"{API}/x/v2/reply?type=1&oid={d['aid']}&sort=1&ps=20&pn=1").get("data") or {}
        rows = sorted(data.get("replies") or [], key=lambda c: -(c.get("like") or 0))[:COMMENTS]
        return "".join(f"\n- （{c.get('like', 0)} 赞）{(c.get('content') or {}).get('message', '').strip()[:COMMENT_CHARS]}" for c in rows)

    part("点赞最多的评论", comments)
    return "\n".join(out)
