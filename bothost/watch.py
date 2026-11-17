"""Watching a video for the model: the project's video reader (plugins/astrbot_plugin_video_reader: download,
shrink, cut into pieces, one Gemini call per piece, merge; for a Bilibili link also the page's text) behind a tool call.

A site that refuses the downloader is asked again with the cookies of the bot's own browser (visitor cookies,
or a login made there once), when page reading has a browser.

A video can take longer than a tool call may. The work then goes on, and the same call made again gets its result.
"""
from __future__ import annotations

import asyncio
import time

from plugins.astrbot_plugin_video_reader import video

from . import web

WAIT_S = 160.0   # the tool bridge allows 180 s


class Watcher:
    def __init__(self, wait: float | None = WAIT_S, **route):
        """route: model, base_url, api_key, and where ffmpeg and yt-dlp are (see video.Config).
        wait: how long one call waits before answering "not done yet"; None: until it is done (with session handoff
        the call runs in a session that no longer holds the group)."""
        self.cfg, self.wait = video.Config(**{k: v for k, v in route.items() if v}), wait
        self.one = asyncio.Lock()   # a download and a transcode at a time: the machine is small
        self.going: dict[tuple, asyncio.Task] = {}

    async def _watch(self, url: str, question: str, start: float | None, end: float | None) -> tuple[str, dict | None]:
        t0 = time.monotonic()
        async with self.one:
            loop = asyncio.get_running_loop()   # the download runs in a thread, the browser lives on this loop

            def jar(folder: str) -> str:
                try:
                    return asyncio.run_coroutine_threadsafe(web.cookies_file(url, folder), loop).result(90)
                except Exception:   # no cookies is an answer: the first refusal is what gets reported
                    return ""

            text, used = await asyncio.to_thread(video.watch, self.cfg, url, question, start, end, jar)
        return text, {**used, "seconds": round(time.monotonic() - t0, 1)} if used else None

    async def ask(self, url: str, question: str, start: float = -1, end: float = -1) -> tuple[str, dict | None]:
        """The answer and the model use; the use is None when nothing finished in this call."""
        try:
            url = video.public_url(url)
        except (video.VideoError, OSError) as e:
            return f"失败：{e}", None
        key = (url, question.strip(), start, end)
        task = self.going.get(key) or asyncio.create_task(self._watch(url, question, start if start >= 0 else None, end if end > 0 else None))
        self.going[key] = task
        try:
            out = await asyncio.wait_for(asyncio.shield(task), self.wait)
        except asyncio.TimeoutError:
            return "还没看完（视频要下载、压缩再看，长视频会久一些）。过一两分钟用完全相同的参数再调一次就能拿到结果；现在不要编视频内容。", None
        except video.VideoError as e:
            out = f"失败：{e}。不要凭印象补视频内容。", None
        except Exception as e:
            out = f"失败：看视频出错（{type(e).__name__}）。不要凭印象补视频内容。", None
        del self.going[key]
        return out
