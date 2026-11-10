"""AstrBot plugin: local web page reader (text + links, SSRF guarded) and a browser for the model.

Unlike the black-box DeepSeek fetch API, `web_reader` returns the page's links, so the model
can navigate a site (homepage -> article). When a site answers with a bot check, reading
escalates: plain request -> browser TLS fingerprint (curl_cffi) -> real Chrome (patchright) ->
Camoufox (Firefox, when installed), each step only if the previous one hit a wall. `browser_*`
tools let the model use a page (questionnaires, small quiz/game pages). Read-only toward the
host: no shell, no files, no downloads; every browser connection goes through a local proxy
that refuses non-public addresses.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

from . import browser as br
from .reader import BlockedURL, BotWall, FetchError, extract, fetch, fetch_impersonate, format_result


@register(
    "astrbot_plugin_web_reader",
    "qqbot",
    "本地读取网页正文和链接（带 SSRF 防护、反爬逐级升级），并能用浏览器操作网页",
    "0.4.0",
)
class WebReaderPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None) -> None:
        super().__init__(context)
        c = config or {}
        self.browser_enabled = bool(c.get("browser_enabled", True)) and br.available()
        profile = c.get("browser_profile_dir") or ""
        if not profile:
            try:
                from astrbot.core.utils.astrbot_path import get_astrbot_data_path
                profile = str(Path(get_astrbot_data_path()) / "web_reader_browser")
            except Exception:  # noqa: BLE001
                profile = str(Path.home() / ".cache" / "web_reader_browser")
        common = dict(
            headless=bool(c.get("browser_headless", False)),
            locale=c.get("browser_locale") or "zh-CN",
            timezone=c.get("browser_timezone", ""),
            xvfb_command=c.get("xvfb_command") or "Xvfb",
            challenge_wait=float(c.get("challenge_wait_seconds", 45)),
        )
        self.browser = br.Browser(br.BrowserConfig(
            profile_dir=profile, executable_path=c.get("browser_executable", ""), **common))
        # second engine for the fetch tier only; started on first use
        self.fox = None
        if self.browser_enabled and bool(c.get("camoufox_enabled", True)) and br.available("camoufox"):
            self.fox = br.Browser(br.BrowserConfig(profile_dir=profile + "_camoufox", engine="camoufox", **common))
        self.sessions: dict[str, br.Session] = {}

    async def terminate(self):
        for s in self.sessions.values():
            await s.close()
        await self.browser.close()
        if self.fox is not None:
            await self.fox.close()

    @staticmethod
    def _too_thin(ctype: str, raw: bytes, url: str) -> bool:
        """An HTML page whose main text is nearly empty: JS-rendered or a disguised check page."""
        if "html" not in ctype.lower():
            return False
        try:
            return extract(raw, url, 0, 2000)["total"] < 200
        except Exception:  # noqa: BLE001
            return False

    async def _read_html(self, url: str) -> tuple[str, str, bytes, str]:
        """(final_url, content_type, body, how) through the escalation tiers. A tier that returns
        a nearly empty HTML page counts as not good enough when the browser can still try."""
        thin = None
        try:
            final, ctype, raw = await asyncio.to_thread(fetch, url)
            if not (self.browser_enabled and self._too_thin(ctype, raw, final)):
                return final, ctype, raw, ""
            thin = (final, ctype, raw, "")
        except BotWall:
            pass
        try:
            final, ctype, raw = await asyncio.to_thread(fetch_impersonate, url)
            if not (self.browser_enabled and self._too_thin(ctype, raw, final)):
                return final, ctype, raw, "（经浏览器指纹请求读取）"
            thin = thin or (final, ctype, raw, "（经浏览器指纹请求读取）")
        except BotWall:
            pass
        except FetchError as exc:
            if "未安装" not in str(exc):
                logger.info(f"web_reader impersonate tier: {exc}")
        if not self.browser_enabled:
            raise BotWall("网站有反爬验证，且未启用浏览器")
        for b, how in ((self.browser, "（经浏览器读取）"), (self.fox, "（经第二浏览器读取）")):
            if b is None:
                continue
            try:
                final, html, passed = await b.fetch_rendered(url)
            except PermissionError:
                raise
            except Exception as exc:  # noqa: BLE001 - this engine failed; the next may not
                logger.info(f"web_reader browser tier ({b.cfg.engine}): {exc!r}")
                continue
            if passed:
                return final, "text/html", html.encode("utf-8"), how
        if thin:
            return thin
        raise BotWall("网站的人机验证没有通过（可能是当前网络 IP 被拦，或访问太频繁）")

    @filter.llm_tool(name="web_reader")
    async def web_reader(
        self,
        event: AstrMessageEvent,
        url: str,
        offset: int = 0,
        links_offset: int = 0,
        limit: int = 6000,
    ) -> str:
        """读取一个网页的正文和页面内链接（本地抓取，返回内容+链接列表，适合“看看这个网站/文章”）。

        用法建议：用户给出 URL 时用它；如果返回的是网站首页/目录（正文很短、链接很多），
        从 links 里挑具体文章 URL 再调用一次；正文被截断时用 offset 继续读；
        链接被截断（提示 links_more）时用 links_offset 继续读更多链接（正文区链接排在前面）。
        遇到反爬会自动换浏览器读取，会慢一些。需要点按钮、填表、翻页互动的网页用 browser_open。
        如果要在回答里引用网页原文，先确认这段原文出现在本次返回的 content 里；没看到就用 offset 续读，
        不要凭记忆或猜测补全网页内容。如果抓取失败或内容不相关，按你平时的口吻自然回应（比如网不好、等会儿看）。

        Args:
            url(string): 要读取的完整 http/https URL
            offset(number): 正文起始字符偏移，默认 0；用于续读长文
            links_offset(number): 链接列表起始位置，默认 0；返回里提示 links_more 时用它续读
            limit(number): 本次最多返回的正文长度（500-12000），默认 6000
        """
        url = (url or "").strip()
        if not url:
            return "错误：url 为空"
        try:
            final_url, ctype, raw, how = await self._read_html(url)
            if "html" not in ctype.lower() and "text" not in ctype.lower():
                return f"错误：不支持的内容类型 {ctype or '(unknown)'}"
            data = await asyncio.to_thread(
                extract, raw, final_url, int(offset or 0), int(limit or 6000), int(links_offset or 0)
            )
            return (how + "\n" if how else "") + format_result(data)
        except (BlockedURL, PermissionError) as exc:
            return f"错误：{exc}"
        except FetchError as exc:
            return f"错误：{exc}"
        except Exception as exc:  # noqa: BLE001 - tool must return text
            return f"错误：读取/解析失败（{exc.__class__.__name__}）"

    # ---- interactive browser -------------------------------------------------------------

    def _session(self, event: AstrMessageEvent) -> br.Session:
        now = time.time()
        for k in [k for k, s in self.sessions.items() if now - s.last_used > br.IDLE_SECONDS]:
            asyncio.ensure_future(self.sessions.pop(k).close())
        key = event.unified_msg_origin
        if key not in self.sessions:
            self.sessions[key] = br.Session(self.browser)
        return self.sessions[key]

    async def _guarded(self, coro) -> str:
        if not self.browser_enabled:
            return "错误：浏览器未启用（未安装 patchright 或配置关闭）"
        try:
            return await coro
        except Exception as exc:  # noqa: BLE001 - tool must return text
            logger.warning(f"browser tool failed: {exc!r}")
            return f"错误：浏览器操作失败（{exc.__class__.__name__}）"

    @filter.llm_tool(name="browser_open")
    async def browser_open(self, event: AstrMessageEvent, url: str) -> str:
        """在浏览器里打开网页并返回页面结构快照（元素带 [ref=eN] 编号），用于需要点击、填写、选择的网页，
        比如问卷、小测试、网页小游戏、要点“展开/下一页”才出内容的页面。只读文章用 web_reader 更快。
        之后用 browser_click / browser_type / browser_select / browser_key 按 ref 操作；每次操作都会返回新快照，
        ref 可能变化，以最新快照为准。不要替群友填写真实个人信息（手机号、身份证、住址、账号密码），
        不要做付款、登录、发帖等会产生后果的提交；遇到这些停下来说明。

        Args:
            url(string): 完整 http/https URL
        """
        return await self._guarded(self._session(event).open((url or "").strip()))

    @filter.llm_tool(name="browser_click")
    async def browser_click(self, event: AstrMessageEvent, ref: str) -> str:
        """点击当前页面快照里编号为 ref 的元素（按钮、链接、单选/多选项等），返回新快照。

        Args:
            ref(string): 快照里的元素编号，如 e12
        """
        return await self._guarded(self._session(event).act("click", ref))

    @filter.llm_tool(name="browser_type")
    async def browser_type(self, event: AstrMessageEvent, ref: str, text: str, submit: bool = False) -> str:
        """在编号为 ref 的输入框里填入文字（会先清空），submit=true 时再按回车，返回新快照。

        Args:
            ref(string): 输入框的元素编号
            text(string): 要填的内容
            submit(boolean): 填完是否按回车提交，默认 false
        """
        return await self._guarded(self._session(event).act("type", ref, text, bool(submit)))

    @filter.llm_tool(name="browser_select")
    async def browser_select(self, event: AstrMessageEvent, ref: str, values: str) -> str:
        """在下拉框 ref 里选择选项（填选项的文字或值，多选用 | 分隔），返回新快照。

        Args:
            ref(string): 下拉框的元素编号
            values(string): 要选的选项，多个用 | 分隔
        """
        return await self._guarded(self._session(event).act("select", ref, values))

    @filter.llm_tool(name="browser_key")
    async def browser_key(self, event: AstrMessageEvent, action: str, key: str = "") -> str:
        """其他页面操作：action=press 按键（key 如 Enter、ArrowUp、Space），action=back 后退，
        action=snapshot 只看当前页面不操作（页面很长时 key 填返回里提示的起始位置，看后面部分）。

        Args:
            action(string): press / back / snapshot
            key(string): press 时的按键名；snapshot 时可填起始位置数字
        """
        s = self._session(event)
        if action == "snapshot":
            return await self._guarded(s.snapshot(offset=int(key) if str(key).isdigit() else 0))
        return await self._guarded(s.act(action, "", key))

    @filter.llm_tool(name="browser_find")
    async def browser_find(self, event: AstrMessageEvent, text: str) -> str:
        """在当前打开的页面里查找文字，返回包含它的几处页面结构（带 ref），适合长页面里找某一楼、某一条、某个按钮。

        Args:
            text(string): 要找的文字（如「第238楼」「提交」）
        """
        return await self._guarded(self._session(event).find(text))
