---
name: web-lookup
description: Look up current or recent information on the web (news, releases, prices, events, people, versions, anything time-sensitive). Use when the user asks to check/search online, asks about recent news, or when an answer may have changed recently.
---

# Web lookup

Use AstrBot's built-in web-search tools; never answer time-sensitive questions from memory.

1. Call `web_search_deepseek` with a short query in the user's language (query supports filters such as `site:`, `lang:`, `after:YYYY-MM-DD`).
2. If the summary of a result is not enough, read it with `deepseek_fetch_web_page` (only for the 1–2 most important results).
3. Reply briefly: 1–3 sentences, group-chat tone. Include 1–2 source names (not full URLs unless asked). Never paste long excerpts.
4. **Do not output citation tags such as `<ref>...</ref>`** — QQ 群聊里会显示成乱码。需要出处时用自然语言，例如「据证券时报报道」。
5. If results conflict or search fails, say so briefly instead of making something up.
6. Do not use this skill for casual chit-chat or stable knowledge (math, code, definitions).
