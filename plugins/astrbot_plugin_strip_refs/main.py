"""Strip AstrBot web-search citation tags from outgoing replies.

AstrBot's web-search prompt asks the model to cite with ``<ref>index</ref>``.
That format is useful in the dashboard but shows up as literal junk in QQ
messages, so we remove it at the plugin layer (no core changes, decision D-002).

Scope: only the outgoing result chain; does not touch tool results or memory.
"""

from __future__ import annotations

import re

from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Plain
from astrbot.api.star import Context, Star, register

REF_RE = re.compile(r"<ref>.*?</ref>", re.S)


@register(
    "astrbot_plugin_strip_refs",
    "qqbot",
    "移除回复中的 <ref></ref> 引用标记（QQ 群聊显示友好）",
    "0.1.0",
)
class StripRefsPlugin(Star):
    def __init__(self, context: Context) -> None:
        super().__init__(context)

    @filter.on_decorating_result()
    async def strip_refs(self, event: AstrMessageEvent) -> None:
        result = event.get_result()
        if result is None or not result.chain:
            return
        for comp in result.chain:
            if isinstance(comp, Plain) and "<ref>" in comp.text:
                cleaned = REF_RE.sub("", comp.text)
                cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()
                comp.text = cleaned
