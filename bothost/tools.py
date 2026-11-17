"""The tools the model gets, served over MCP: by the bot process (HTTP, one caller per group) or on their own
over stdio (`python -m bothost.tools --db ...`) for a harness session that has no group, such as a test chat."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import threading
from pathlib import Path
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import TYPE_CHECKING

from mcp.server.mcpserver import MCPServer

from bench.store.frozen import FrozenMemory

from . import lookup, people, sessions, watch, web
from .store import TZ, Store, line, stamp

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .app import Host


def build(store: Store, host: "Host | None" = None, current: Callable[[], str] = lambda: "", exclude: tuple[str, ...] = (),
          web_key: str = "", lookup: Callable[[str, str], Awaitable[str]] | None = None,
          private: tuple[str, Callable[[], str]] | None = None,
          video: Callable[[str, str, float, float], Awaitable[str]] | None = None) -> MCPServer:
    """current() names the caller's group; when it is empty the most recently active group stands in.

    private: the code of a one-on-one chat and a function that brings it up to date and names the caller's session.
    With it the tools serve such a chat: the context shows the earlier sessions' last lines, the search covers all of them.
    """
    server = MCPServer("qq")
    frozen = FrozenMemory(store.path)
    threading.Thread(target=frozen.load, daemon=True).start()   # about ten seconds for the imported groups; ready before the first question

    dm = private[0] if private else ""
    where = lambda code: f"私聊 {code}（和对方一对一聊过的话，包括以前的会话）" if code == dm else f"群 {code}"

    if host is not None:
        @server.tool(description="往当前群里发一条消息。这是在群里说话的唯一方式。")
        async def send_group_message(text: str) -> str:
            return await host.send(text)

    @server.tool(description="加载记忆背景：能回忆的群和各自的时间范围、现在的时间，以及当前群最近的一段聊天。"
                             "需要确认「现在」和最近发生了什么时调用；更早的细节用 memory_search。")
    async def memory_context(count: int = 40) -> str:
        session = private[1]() if private else ""
        groups = store.catalog(exclude)
        if not groups:
            return "还没有任何聊天记录。"
        here = private[0] if private else current() or groups[0]["code"]
        tail = store.recent(here, max(10, min(int(count), 80)), skip=session)
        now = datetime.now(TZ).timestamp()
        out = ["【能回忆的聊天】" if private else "【能回忆的群】"] + [f"- {where(g['code'])}：{g['messages']} 条，{stamp(g['first'])} ~ {stamp(g['last'])}"
                               + ("" if g["code"] == dm else f"，约 {g['people']} 人") for g in groups]
        out += [f"【现在】{stamp(now)}（北京时间）", "",
                f"【之前几次私聊的最后 {len(tail)} 条（不含这一次）】" if private else f"【「{here}」群最近的 {len(tail)} 条】"]
        return "\n".join(out + [line(r["ts"], r["name"] or "?", r["text"]) for r in tail])

    @server.tool(description="在群聊历史里回忆：用一句话或几个关键词，检索待过的所有群。整理过的历史按话题找，每个群返回最相关的几段原话（带群代号、时间范围、发言人）；"
                             "还没整理的近期消息逐条找，返回命中的那一句和前后文，limit 是这部分的条数。"
                             "用于「之前说过什么」「那个人是谁」「那次发生了什么」这类问题。groups 可填逗号分隔的群代号来限定范围，不填就查所有群；"
                             "as_of 可填 ISO 时间，只看那之前的消息。引用要与原文一致，查不到就说没印象，不要编。")
    async def memory_search(query: str, groups: str = "", as_of: str = "", limit: int = 6) -> str:
        if not query.strip():
            return "query 不能为空。"
        try:
            before = datetime.fromisoformat(as_of).timestamp() if as_of.strip() else float("inf")
        except ValueError:
            return "as_of 要写成 ISO 时间，例如 2026-01-31T12:00:00+08:00。"
        only = tuple(g.strip() for g in groups.split(",") if g.strip())
        if private:
            private[1]()
        out = [f"范围：{'、'.join(only) or '所有群'}。"]
        try:   # the frozen version over the coloured history; a question vector is fetched, so off the event loop
            found, vectors = await asyncio.to_thread(frozen.search, query.strip(), before, only, exclude)
            newer = {code: g.end_ts for code, g in frozen.load().items()}
            if not vectors:
                out.append("（向量服务没连上，整理过的部分这次只按关键词找。）")
        except Exception as e:
            log.exception("frozen retrieval failed")
            found, newer = {}, None
            out.append(f"（按话题整理的索引用不了：{type(e).__name__}。这次全部按关键词逐条找。）")
        n = 0
        for code, blocks in found.items():
            if blocks:
                out.append(f"\n【群 {code} · 按话题找到 {len(blocks)} 段，越靠前越相关】")
            for part in blocks:
                n += 1
                out.append(f"#{n} {stamp(part[0].timestamp)} ~ {stamp(part[-1].timestamp)}")
                out += [f"{m.nickname_at_time or '?'}: {m.content}" for m in part]
        hits = store.search(query.strip(), max(1, min(int(limit), 12)), only, before, exclude, newer=newer)
        if hits:
            out.append(f"\n【{'还没整理的消息' if newer else '逐条'} · 命中 {len(hits)} 处】「>」是命中的那一句，其余是前后文。")
        for h in hits:
            n += 1
            out.append(f"#{n} {'私聊' if h['chat'] == dm else '群'} {h['chat']}")
            out += [("> " if r["hit"] else "  ") + line(r["ts"], r["name"], r["text"], "%Y-%m-%d %H:%M") for r in h["lines"]]
        return "\n".join(out) if n else f"没有查到（范围：{'、'.join(only) or '所有群'}）。"

    @server.tool(description="记住一个人：name 写群消息前面显示的那个名字。知道了别人怎么称呼 ta（外号）、对 ta 有了印象或态度、"
                             "发现两个名字其实是同一个人时调用。只写你真的从聊天里看出来的，不要猜。印象和态度会替换你以前记的；外号会累加。"
                             "记下的内容以后每次都会给你看，也跨群通用。")
    async def note_person(name: str, alias: str = "", impression: str = "", attitude: str = "", same_as: str = "") -> str:
        if not (alias or impression or attitude or same_as).strip():
            return "至少要填外号、印象、态度、同一个人当中的一项。"
        here = private[0] if private else current()
        persons = people.resolve(store.db, name, here)
        if not persons:
            return f"没找到群里叫「{name}」的人。name 要写群消息前面显示的名字。"
        done = people.apply(store.db, [{"name": name, "alias": alias, "impression": impression, "attitude": attitude, "same_as": same_as}],
                            "tool", here)
        return ("记下了。" if done["recorded"] else "这些你已经记过了。") + "\n" + people.entry(store.db, persons[0])

    @server.tool(description="查一个人：用群里显示的名字或外号查，返回 ta 在群里显示过的名字、你记下的外号、印象和态度。"
                             "有人提到一个你对不上号的名字或外号时用。")
    async def who_is(name: str) -> str:
        persons = people.resolve(store.db, name, private[0] if private else current())
        if not persons:
            return f"不认识「{name}」：群里没人用这个名字，你也没记过这个外号。可以用 memory_search 搜一下原话。"
        head = "" if len(persons) == 1 else f"有 {len(persons)} 个人可能是，按可能性排：\n"
        return head + "\n".join(people.entry(store.db, p) for p in persons[:3])

    if lookup is not None:
        @server.tool(description="联网查证：把要查的问题或网址交出去，拿回一段几百字的结论和依据网址。用于核实可能过时的事实（版本号、发布公告、价格、政策、最新状态）"
                                 "和群友发来的链接。问题要写完整，带上必要的名字和时间，对方看不到群里的聊天。纯闲聊和稳定常识不要用。"
                                 "一次可能要等几十秒到两分钟。回来的除了结论，还有它搜了什么、哪些网页读到了哪些没读到，以及一个编号。"
                                 "结论不够用、缺了你要的细节、或者想让它换个来源再查时，再调一次，follow_up 填那个编号，question 写清楚还要什么："
                                 "它会接着上次读到的内容继续，不用从头来。结论说没查到就是没查到，不要凭记忆补答案。")
        async def look_up(question: str, follow_up: str = "") -> str:
            return await lookup(question, follow_up) if question.strip() else "question 不能为空。"
    elif web_key:   # a session without a helper gets the raw results
        @server.tool(description="联网搜索当前信息。用于核实可能过时的事实：版本号、发布公告、价格、政策、最新状态。纯闲聊和稳定常识不要用。"
                                 "支持 site: / after: / before: / lang: 等语法。结果为空、过旧或无关就换关键词再查，不要凭记忆补答案。")
        async def search_web(query: str, count: int = 8, need_content: bool = False) -> str:
            return await web.search(web_key, query, count, need_content)

        @server.tool(description="读取一个已知网址的正文。用于群友发来的链接，或搜索结果里需要读全文的页面。读不到就说读不到，不要编造页面内容。")
        async def fetch_page(url: str) -> str:
            return await web.fetch(web_key, url)

    if video is not None:
        @server.tool(description="看一个视频并回答问题：给视频页面的链接（B 站、YouTube 等）和想知道的事，拿回看到、听到的内容，时间是原视频时间；B 站链接还会带回简介、标签和点赞最多的评论。"
                                 "群友发了视频、你好奇或者有人想让你看时用，不必等人问；文字网页用 look_up，不要用这个。question 写具体。"
                                 "视频要下载、压缩再看，短的几十秒，长的几分钟；问题里有「第几分钟」这类线索时填 start_seconds/end_seconds 只看那一段，"
                                 "超过 3 小时的视频必须填。回复说还没看完时，过一两分钟用完全相同的参数再调一次。"
                                 "说视频内容只用这里返回的，没看到的不要编。")
        async def watch_video(url: str, question: str, start_seconds: float = -1, end_seconds: float = -1) -> str:
            return await video(url, question, start_seconds, end_seconds) if url.strip() and question.strip() else "url 和 question 都要填。"

    return server


def main() -> None:
    ap = argparse.ArgumentParser(description="Memory (and, given a search key, web) tools over stdio, without a group.")
    ap.add_argument("--db", required=True)
    ap.add_argument("--exclude", default="", help="group codes left out of recall, comma-separated")
    ap.add_argument("--web-key-file", help="file holding the search key, for launchers that strip keys from the environment")
    ap.add_argument("--lookup-model", help="with a key: web look-ups run in a conversation of their own on this model, and only the conclusion is returned")
    ap.add_argument("--lookup-base-url", default="https://api.deepseek.com/v1")
    ap.add_argument("--usage-file", help="one line per look-up: model calls and tokens")
    ap.add_argument("--lookup-timeout", type=float, default=150.0)
    ap.add_argument("--browser-profile", help="folder for a browser profile: with it, pages that answer with a bot check are read in a real browser")
    ap.add_argument("--browser-executable", default=os.environ.get("BROWSER_EXECUTABLE", ""))
    ap.add_argument("--xvfb", default=os.environ.get("XVFB_COMMAND", "Xvfb"))
    ap.add_argument("--video-model", help="with it, videos are watched by this Gemini model (native generateContent, video inline)")
    ap.add_argument("--video-base-url", default="")
    ap.add_argument("--video-key-file", help="default: VIDEO_READER_API_KEY, else the local proxy's own key")
    ap.add_argument("--ffmpeg", default=os.environ.get("VIDEO_READER_FFMPEG", ""))
    ap.add_argument("--ytdlp", default=os.environ.get("VIDEO_READER_YTDLP", ""))
    ap.add_argument("--sessions", help="the harness's session folder: sessions of --sessions-preset are one private chat that later sessions recall")
    ap.add_argument("--sessions-preset", default="test")
    ap.add_argument("--sessions-code", default=sessions.CODE, help="the chat code the private chat is stored under")
    args = ap.parse_args()
    exclude = tuple(c for c in args.exclude.split(",") if c)
    key = Path(args.web_key_file).read_text().strip() if args.web_key_file else os.environ.get("QQBOT_SEARCH_API_KEY", "")
    def log_use(model: str, what: str, use: dict) -> None:
        if args.usage_file:
            with open(args.usage_file, "a", encoding="utf-8") as f:
                f.write(json.dumps({"started": datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S"), "model": model, what: use}, ensure_ascii=False) + "\n")

    helper = None
    if args.browser_profile and not web.use_browser(args.browser_profile, args.browser_executable, args.xvfb):
        log.warning("the browser library is not installed; pages behind a bot check will not be read")
    if key and args.lookup_model:   # the same key pays for the helper's model calls
        asked = lookup.Lookups(model=args.lookup_model, base_url=args.lookup_base_url, llm_key=key, web_key=key, timeout=args.lookup_timeout)

        async def helper(question: str, follow_up: str = "") -> str:
            answer, used = await asked.ask(question, follow_up)
            log_use(args.lookup_model, "lookup", {k: v for k, v in used.items() if k != "steps"})
            return answer
    video = None
    if args.video_model:
        if args.video_key_file:
            video_key = Path(args.video_key_file).read_text().strip()
        elif not (video_key := os.environ.get("VIDEO_READER_API_KEY", "")):
            from bench.llm import api_key
            video_key = api_key()
        watcher = watch.Watcher(model=args.video_model, base_url=args.video_base_url, api_key=video_key, ffmpeg=args.ffmpeg, ytdlp=args.ytdlp)

        async def video(url: str, question: str, start: float, end: float) -> str:
            answer, use = await watcher.ask(url, question, start, end)
            if use:
                log_use(args.video_model, "video", use)
            return answer
    store, private = Store(args.db), None
    if args.sessions:
        private = (args.sessions_code, lambda: sessions.sync(store, Path(args.sessions), args.sessions_preset, args.sessions_code))
        private[1]()
    build(store, exclude=exclude, web_key=key, lookup=helper, private=private, video=video).run("stdio")

if __name__ == "__main__":
    main()
