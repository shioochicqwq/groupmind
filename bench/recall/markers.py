"""Surface patterns that suggest a message recalls something. A prefilter only: the labelling
model decides, so the patterns lean toward catching too much (「记得带伞」 is caught and thrown out later)."""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence

from bench.sanitize import is_sensitive
from bench.schema import Message

_WHO = "你|他|她|我|谁|有人|群里"
CATEGORIES: dict[str, re.Pattern] = {
    # says they remember, or that it comes back to them
    "remember": re.compile(r"我记得|还记得|记不记得|记得.{0,8}(说过|讲过|发过|提过|好像|是不是|当时|上次|之前|以前)|想起|印象[中里]|有印象"),
    # says they forgot or cannot recall
    "forgot": re.compile(r"忘了|忘记|记不清|记不得|记不起|想不起|不记得|没印象"),
    # the particle used when groping for something once known
    "laizhe": re.compile(r"来着"),
    # points at an earlier occasion
    "past": re.compile(r"上次|上回|那次|那回|那天|那会|当时|当年|之前|以前|前[几两]天|前阵子|前段时间|(昨天|前天|昨晚|早上|刚才).{0,6}(说|讲|聊|发|提)"),
    # asks or states who said something earlier
    "source": re.compile(rf"谁(说|发|讲)(的|过)|({_WHO}).{{0,4}}(说过|讲过|发过|提过|提到过)|不是说|说好的|早就说|哪来的"),
    # a hedged impression
    "vague": re.compile(r"好像.{0,6}(说过|讲过|发过|提过|有人)|依稀|隐约"),
}


_MARKDOWN = re.compile(r"\*\*.+?\*\*|^#+ |\n- ", re.M)


def categories(text: str) -> list[str]:
    return [name for name, rx in CATEGORIES.items() if rx.search(text)]


def candidates(messages: Sequence[Message], max_chars: int = 400) -> list[tuple[int, list[str]]]:
    """(position in `messages`, categories) for every message that matches. Messages must be cleaned
    (bench.tasks.real_tasks.clean_messages) and in time order."""
    out = []
    for i, m in enumerate(messages):
        if not m.content or len(m.content) > max_chars or is_sensitive(m.content):
            continue
        cats = categories(m.content)
        if cats:
            out.append((i, cats))
    return out


def program_like(messages: Sequence[Message], min_msgs: int = 20, md_share: float = 0.1, mean_chars: float = 80) -> set[str]:
    """Author ids that write like a program (a bot in the group): many messages with markdown
    formatting, or a mean length far above a chat message. Their text is not a person's recall."""
    n, md, chars = Counter(), Counter(), Counter()
    for m in messages:
        if m.content:
            n[m.author] += 1
            md[m.author] += bool(_MARKDOWN.search(m.content))
            chars[m.author] += len(m.content)
    return {a for a in n if n[a] >= min_msgs and (md[a] / n[a] > md_share or chars[a] / n[a] > mean_chars)}


def counts(found: Sequence[tuple[int, list[str]]]) -> dict[str, int]:
    c = Counter(cat for _, cats in found for cat in cats)
    return {"any": len(found), **{k: c.get(k, 0) for k in CATEGORIES}}
