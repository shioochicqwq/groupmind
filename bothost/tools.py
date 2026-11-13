"""The tools the model gets, served over MCP: by the bot process (HTTP, one caller per group) or on their own
over stdio (`python -m bothost.tools --db ...`) for a harness session that has no group, such as a test chat."""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import threading
from pathlib import Path
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import TYPE_CHECKING

from mcp.server.mcpserver import MCPServer

from bench.store.frozen import FrozenMemory

from . import web
from .store import TZ, Store, line, stamp

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .app import Host


def build(store: Store, host: "Host | None" = None, current: Callable[[], str] = lambda: "", exclude: tuple[str, ...] = (),
          web_key: str = "", lookup: Callable[[str], Awaitable[str]] | None = None) -> MCPServer:
    """current() names the caller's group; when it is empty the most recently active group stands in."""
    server = MCPServer("qq")
    frozen = FrozenMemory(store.path)
    threading.Thread(target=frozen.load, daemon=True).start()   # about ten seconds for the imported groups; ready before the first question

    if host is not None:
        @server.tool(description="往当前群里发一条消息。这是在群里说话的唯一方式。")
        async def send_group_message(text: str) -> str:
            return await host.send(text)

    @server.tool(description="加载记忆背景：能回忆的群和各自的时间范围、现在的时间，以及当前群最近的一段聊天。"
                             "需要确认「现在」和最近发生了什么时调用；更早的细节用 memory_search。")
    async def memory_context(count: int = 40) -> str:
        groups = store.catalog(exclude)
        if not groups:
            return "还没有任何聊天记录。"
        here = current() or groups[0]["code"]
        tail = store.recent(here, max(10, min(int(count), 80)))
        now = datetime.now(TZ).timestamp() if host is not None else groups[0]["last"]   # a test chat lives at the end of the record
        out = ["【能回忆的群】"] + [f"- {g['code']}：{g['messages']} 条，{stamp(g['first'])} ~ {stamp(g['last'])}，约 {g['people']} 人" for g in groups]
        out += [f"【现在】{stamp(now)}（北京时间）", "", f"【「{here}」群最近的 {len(tail)} 条】"]
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
            out.append(f"#{n} 群 {h['chat']}")
            out += [("> " if r["hit"] else "  ") + line(r["ts"], r["name"], r["text"], "%Y-%m-%d %H:%M") for r in h["lines"]]
        return "\n".join(out) if n else f"没有查到（范围：{'、'.join(only) or '所有群'}）。"

    if lookup is not None:
        @server.tool(description="联网查证：把要查的问题或网址交出去，拿回一段几百字的结论和依据网址。用于核实可能过时的事实（版本号、发布公告、价格、政策、最新状态）"
                                 "和群友发来的链接。问题要写完整，带上必要的名字和时间，对方看不到群里的聊天。纯闲聊和稳定常识不要用。"
                                 "一次可能要等几十秒。结论说没查到就是没查到，不要凭记忆补答案。")
        async def look_up(question: str) -> str:
            return await lookup(question) if question.strip() else "question 不能为空。"
    elif web_key:   # a session without a helper gets the raw results
        @server.tool(description="联网搜索当前信息。用于核实可能过时的事实：版本号、发布公告、价格、政策、最新状态。纯闲聊和稳定常识不要用。"
                                 "支持 site: / after: / before: / lang: 等语法。结果为空、过旧或无关就换关键词再查，不要凭记忆补答案。")
        async def search_web(query: str, count: int = 8, need_content: bool = False) -> str:
            return await web.search(web_key, query, count, need_content)

        @server.tool(description="读取一个已知网址的正文。用于群友发来的链接，或搜索结果里需要读全文的页面。读不到就说读不到，不要编造页面内容。")
        async def fetch_page(url: str) -> str:
            return await web.fetch(web_key, url)

    return server


def main() -> None:
    ap = argparse.ArgumentParser(description="Memory (and, given a search key, web) tools over stdio, without a group.")
    ap.add_argument("--db", required=True)
    ap.add_argument("--exclude", default="", help="group codes left out of recall, comma-separated")
    ap.add_argument("--web-key-file", help="file holding the search key, for launchers that strip keys from the environment")
    args = ap.parse_args()
    exclude = tuple(c for c in args.exclude.split(",") if c)
    key = Path(args.web_key_file).read_text().strip() if args.web_key_file else os.environ.get("QQBOT_SEARCH_API_KEY", "")
    build(Store(args.db), exclude=exclude, web_key=key).run("stdio")


if __name__ == "__main__":
    main()
