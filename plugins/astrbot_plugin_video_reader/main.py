"""AstrBot plugin: watch a video for the model (download, shrink, split, ask Gemini, merge).

The model passes a public video URL (Bilibili, YouTube or anything yt-dlp supports) and a
question; a video sent in the chat is picked up when the URL is left empty. Local paths from
the model are never accepted, and URL hosts must resolve to public addresses.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

from . import video


def _public_url(url: str) -> str:
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise video.VideoError("只接受公开的 http/https 视频链接")
    for info in socket.getaddrinfo(parts.hostname, parts.port or 443, proto=socket.IPPROTO_TCP):
        addr = ipaddress.ip_address(info[4][0])
        if addr.version == 6 and addr.ipv4_mapped:
            addr = addr.ipv4_mapped
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved or addr.is_multicast or addr.is_unspecified:
            raise video.VideoError("禁止访问本机/内网地址")
    return url.strip()


def _chat_video_url(event: AstrMessageEvent) -> str:
    """URL of a video in the current message or the message it replies to, if any."""
    def scan(chain) -> str:
        for comp in chain or []:
            name = comp.__class__.__name__
            if name == "Video":
                for attr in ("url", "file"):
                    v = getattr(comp, attr, "") or ""
                    if v.startswith(("http://", "https://")):
                        return v
            if name == "Reply":
                found = scan(getattr(comp, "chain", None))
                if found:
                    return found
        return ""
    return scan(getattr(event.message_obj, "message", None))


@register("astrbot_plugin_video_reader", "qqbot", "看视频：下载、压缩、按大小切片后交给 Gemini，回答带原视频时间", "0.1.0")
class VideoReaderPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None) -> None:
        super().__init__(context)
        c = config or {}
        self.cfg = video.Config(
            base_url=c.get("base_url", video.Config.base_url),
            api_key=c.get("api_key", ""),
            model=c.get("model", video.Config.model),
            ffmpeg=c.get("ffmpeg", "ffmpeg"),
            ytdlp=c.get("ytdlp", "yt-dlp"),
            cookies_file=c.get("cookies_file", ""),
            proxy=c.get("proxy", ""),
            workers=int(c.get("workers", 3)),
        )
        self._lock = asyncio.Semaphore(int(c.get("max_concurrent_videos", 1)))

    @filter.llm_tool(name="video_reader")
    async def video_reader(self, event: AstrMessageEvent, question: str, url: str = "",
                           start_seconds: float = -1, end_seconds: float = -1) -> str:
        """看一个视频并回答问题（会下载视频、压缩、按大小切成几段分别看，再合并；回答里的时间是原视频时间）。

        用法：群友发了视频链接（B 站、YouTube 等）或直接发了视频、问视频内容时用。url 留空表示看当前消息
        或被回复消息里的视频。很长的视频（超过 3 小时）必须给 start_seconds/end_seconds 只看一段；
        问题里有“第几分钟”之类的线索时也尽量只看那一段，更快更准。视频要花几十秒到几分钟。
        回答视频内容时只用本工具返回的内容，没看到的不要编。

        Args:
            question(string): 想从视频里知道什么，写具体（例如“UP 主最后推荐了哪款耳机，为什么”）
            url(string): 视频页面链接；留空 = 当前消息里的视频
            start_seconds(number): 只看这一段时的开始秒数；不限制填 -1
            end_seconds(number): 只看这一段时的结束秒数；不限制填 -1
        """
        try:
            source = _public_url(url) if (url or "").strip() else _chat_video_url(event)
            if not source:
                return "错误：没有给视频链接，当前消息里也没有视频"
            source = _public_url(source)
            start = start_seconds if start_seconds is not None and start_seconds >= 0 else None
            end = end_seconds if end_seconds is not None and end_seconds > 0 else None
            async with self._lock:
                r = await asyncio.to_thread(video.answer, self.cfg, source, question, start, end)
        except video.VideoError as exc:
            return f"错误：{exc}"
        except Exception as exc:  # noqa: BLE001 - tool must return text
            logger.warning(f"video_reader failed: {exc!r}")
            return f"错误：看视频失败（{exc.__class__.__name__}）"
        meta = r["meta"]
        head = f"视频：{meta.get('title') or '(无标题)'}；时长 {video.fmt_ts(meta.get('duration') or 0)}；分 {len(r['segments'])} 段看"
        if meta.get("uploader"):
            head += f"；UP/作者：{meta['uploader']}"
        return f"{head}\n\n{r['answer']}"
