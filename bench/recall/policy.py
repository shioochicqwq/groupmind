"""Route A, second version: how clearly the bot "remembers" each retrieved block.

The store and the retrieval do not change and nothing is deleted. Between retrieval and the answer
model, every block is shown at one of four grains:

  原话      the gist plus the one or two lines that stuck, word for word
  大意      the gist only
  有这回事  the topic only
  不出现    withheld

The grain is decided before the context is built, because a model does not forget what it has been
shown. It follows from the impression the exchange left when it happened (bench.recall.run_impress),
not from how long ago it was: 深 -> 原话, 中 -> 大意, 浅 -> 有这回事, no impression -> 不出现. That
mapping is the definition of the strength scale, not a fitted table. The first version used age
buckets instead; the user rejected that on 2026-11-11 (one may forget the lunch of two days ago and
remember a whole day from two months back).

Three things move a block one grain clearer or keep it from vanishing. All three are PROVISIONAL:
the direction comes from the conversational-memory literature, the size is a placeholder.

  involved   the bot spoke in the exchange or was replied to (own words are remembered better)
  revisited  someone quote-replied to it an hour or more later (what gets talked about again stays)
  fresh      it happened within the last day: still present to mind, at least the gist

An explicit request to look something up ("查一下记录") turns the policy off: precision mode.
"""
from __future__ import annotations

import datetime as dt
import re
from collections.abc import Sequence
from dataclasses import dataclass

from bench.sanitize import is_sensitive
from bench.schema import Block, Message

TIERS = ("原话", "大意", "有这回事", "不出现")
ROLES = ("自己说过", "对自己说的", "旁听")
BY_STRENGTH = {"深": "原话", "中": "大意", "浅": "有这回事", "": "不出现"}
FRESH = 86400       # still present to mind
REVISIT_GAP = 3600  # a reply this long after the message counts as coming back to it
MAX_STUBS = 2       # topic-only items shown at most; more would be noise
OWN_LINES = 2       # of the bot's own lines in an exchange it remembers word for word
LOOKUP = re.compile(r"查(一下|查|下)?.{0,4}(记录|聊天)|翻(一下|翻|下)?.{0,4}(记录|聊天)|原话(是|怎么|到底)|一字不差|原文是")
GUIDE = """下面是你对这个群的记忆，按记得多清楚分成三种：
- 【印象很深】这件事你记得清楚，「还记得的原话」可以直接引用，其余用自己的话说。
- 【记得大意】用自己的话说，不要编出原话，也不要补细节。
- 【只有印象】只知道聊过这件事，细节不记得；可以说「好像聊过」，可以反问对方。
没有列出的就是不记得，照实说不记得，不要猜。没人问起就不主动提旧事。"""
LOOKUP_GUIDE = "对方要求查聊天记录。下面是查到的原文，照原文回答，并说明是查到的而不是记得的。"


@dataclass(frozen=True)
class Evidence:
    block: Block
    role: str
    strength: str          # 深 / 中 / 浅 / "" (no impression)
    fresh: bool
    revisited: bool
    tier: str
    impression: dict | None = None


def precise(query: str) -> bool:
    return bool(LOOKUP.search(query))


def revisits(messages: Sequence[Message]) -> dict[str, float]:
    """msg_id -> time of the first quote-reply that came REVISIT_GAP or more after it."""
    by_id = {m.msg_id: m for m in messages}
    out: dict[str, float] = {}
    for m in messages:
        o = by_id.get(m.reply_to) if m.reply_to else None
        if o is not None and m.timestamp - o.timestamp >= REVISIT_GAP:
            out.setdefault(o.msg_id, m.timestamp)
    return out


def index(impressions: Sequence[dict]) -> dict[str, dict]:
    """msg_id -> the strongest impression that covers it (rows of run_impress)."""
    out: dict[str, dict] = {}
    for imp in sorted(impressions, key=lambda r: "深中浅".index(r["strength"])):
        for i in imp["msg_ids"]:
            out.setdefault(i, imp)
    return out


def role_of(block: Block, by_id: dict[str, Message], me: str) -> str:
    part = [by_id[i] for i in block.msg_ids]
    if any(m.author == me for m in part):
        return "自己说过"
    if any(m.reply_to in by_id and by_id[m.reply_to].author == me for m in part):
        return "对自己说的"
    return "旁听"


def grain(strength: str, involved: bool, revisited: bool, fresh: bool) -> str:
    at = TIERS.index(BY_STRENGTH[strength]) - involved - revisited
    if fresh:
        at = min(at, TIERS.index("大意"))
    return TIERS[max(0, at)]


def decide(blocks: Sequence[Block], by_id: dict[str, Message], impressions: dict[str, dict], revisited: dict[str, float],
           *, me: str, as_of: float, query: str = "") -> list[Evidence]:
    """One Evidence per retrieved block, in the given (ranked) order. `impressions` is index(...)."""
    lookup = precise(query)
    out, stubs, seen = [], 0, set()
    for b in blocks:
        role = role_of(b, by_id, me)
        known = [impressions[i] for i in b.msg_ids if i in impressions and impressions[i]["formed_at"] <= as_of]
        imp = min(known, key=lambda r: "深中浅".index(r["strength"]), default=None)
        fresh = as_of - b.end_ts < FRESH
        back = any(revisited.get(i, float("inf")) < as_of for i in b.msg_ids)
        tier = "原话" if lookup else grain(imp["strength"] if imp else "", role != "旁听", back, fresh)
        if imp is not None and not lookup:
            if id(imp) in seen:
                tier = "不出现"  # the same impression is told once
            seen.add(id(imp))
        if tier == "有这回事":
            stubs += 1
            if stubs > MAX_STUBS:
                tier = "不出现"
        out.append(Evidence(b, role, imp["strength"] if imp else "", fresh, back, tier, imp))
    return out


def topic(summary: str, limit: int = 24) -> str:
    return re.split(r"[，。；,;]", summary.strip(), maxsplit=1)[0][:limit]


def _lines(ids, by_id, seen) -> list[str]:
    out = [f"{by_id[i].author}: {by_id[i].content}" for i in ids
           if i in by_id and i not in seen and by_id[i].content and not is_sensitive(by_id[i].content)]
    seen.update(ids)
    return out


def render(evidence: Sequence[Evidence], by_id: dict[str, Message], summary_of: dict[str, str], as_of: float,
           budget: int, lookup: bool = False, me: str = "") -> tuple[str, list[Evidence]]:
    """The memory section of the answer prompt, within `budget` characters, and what went in."""
    parts, used, shown, seen = [], 0, [], set()
    for e in evidence:
        if e.tier == "不出现":
            continue
        days = max(0, int((as_of - e.block.end_ts) // 86400))
        when = "今天" if days == 0 else f"{days} 天前" if days < 60 else f"约 {days // 30} 个月前"
        gist = (e.impression or {}).get("gist") or summary_of.get(e.block.block_id, "")
        if lookup:
            day = dt.datetime.fromtimestamp(e.block.end_ts, dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d")
            text = f"【聊天记录｜{day}】\n" + "\n".join(_lines(e.block.msg_ids, by_id, seen))
        elif e.tier == "原话":
            own = [i for i in e.block.msg_ids if by_id[i].author == me][:OWN_LINES] if me else []
            kept = _lines(list((e.impression or {}).get("keep", ())) + own, by_id, seen)
            text = f"【印象很深｜{when}】{gist}" + ("\n还记得的原话：\n" + "\n".join(kept) if kept else "")
        elif e.tier == "大意":
            text = f"【记得大意｜{when}】{gist}"
        else:
            text = f"【只有印象｜{when}】聊过：{topic(gist)}"
        if parts and used + len(text) > budget:
            break
        parts.append(text[:budget])
        used += len(text)
        shown.append(e)
    return (LOOKUP_GUIDE if lookup else GUIDE) + "\n\n" + ("\n\n".join(parts) or "（什么都想不起来）"), shown
