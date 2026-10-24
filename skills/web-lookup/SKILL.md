---
name: web-lookup
description: Look up current or recent information on the web (news, releases, prices, events, people, versions) and read specific web pages/sites (articles, blogs, docs). Use when the user asks to check/search online, gives a URL, asks about recent news, or when an answer may have changed recently.
---

# Web lookup

Use AstrBot's built-in web tools; don't answer time-sensitive questions from memory.

1. **用户给了 URL** → 先用 `web_reader` 读它（返回正文+页面链接）。如果正文很短、链接很多（网站首页/目录），从 links 里挑具体的文章/页面 URL 再读一次；正文被截断时用 `offset` 续读。
2. **没有 URL、只是问最近的事** → 用 `web_search_deepseek` 搜索（查询用用户的语言，支持 `site:`、`after:` 等过滤）；从结果里挑 1–2 个重要链接，再用 `web_reader` 或 `deepseek_fetch_web_page` 读正文。
3. 回答保持群友口吻、1–3 句；用到网页内容时自然提一句来源（如「据 XX」或链接），不要输出 `<ref>` 之类标记。
4. 如果抓取失败/超时/内容对不上，可以按你的风格自然推脱（比如网不好、等会儿再看），但**不要编造网页里没有的内容**；需要时换个链接再试一次。
5. 不要用于闲聊或稳定知识（数学、代码、定义）。
