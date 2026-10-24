"""AstrBot plugin: local web page reader (text + links, SSRF guarded).

Unlike the black-box DeepSeek fetch API this tool returns the page's links, so
the model can navigate a site (homepage -> article) instead of only receiving
extracted body text. Read-only; no shell, no files.
"""

from __future__ import annotations

import asyncio

from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

from .reader import BlockedURL, FetchError, extract, fetch, format_result


@register(
    "astrbot_plugin_web_reader",
    "qqbot",
    "本地读取网页正文和链接（带 SSRF 防护），用于看网站/文章",
    "0.1.0",
)
class WebReaderPlugin(Star):
    def __init__(self, context: Context) -> None:
        super().__init__(context)

    @filter.llm_tool(name="web_reader")
    async def web_reader(
        self,
        event: AstrMessageEvent,
        url: str,
        offset: int = 0,
        limit: int = 6000,
    ) -> str:
        """读取一个网页的正文和页面内链接（本地抓取，返回内容+链接列表，适合“看看这个网站/文章”）。

        用法建议：用户给出 URL 时用它；如果返回的是网站首页/目录（正文很短、链接很多），
        从 links 里挑具体文章 URL 再调用一次；正文被截断时用 offset 继续读。
        如果抓取失败或内容不相关，按你平时的口吻自然回应（比如网不好、等会儿看），不要编造网页内容。

        Args:
            url(string): 要读取的完整 http/https URL
            offset(number): 正文起始字符偏移，默认 0；用于续读长文
            limit(number): 本次最多返回的正文长度（500-12000），默认 6000
        """
        url = (url or "").strip()
        if not url:
            return "错误：url 为空"
        try:
            final_url, ctype, raw = await asyncio.to_thread(fetch, url)
            if "html" not in ctype.lower() and "text" not in ctype.lower():
                return f"错误：不支持的内容类型 {ctype or '(unknown)'}"
            data = await asyncio.to_thread(
                extract, raw, final_url, int(offset or 0), int(limit or 6000)
            )
            return format_result(data)
        except BlockedURL as exc:
            return f"错误：{exc}"
        except FetchError as exc:
            return f"错误：{exc}"
        except Exception as exc:  # noqa: BLE001 - tool must return text
            return f"错误：读取/解析失败（{exc.__class__.__name__}）"
