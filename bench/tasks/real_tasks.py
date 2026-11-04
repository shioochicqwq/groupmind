"""Tasks with labels derived automatically from a real group's data."""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import replace

from bench.sanitize import clean_text, strip_mentions
from bench.schema import Message, RetrievalCase, Visibility

HOUR = 3600.0
DAY = 86400.0


def clean_messages(messages: Sequence[Message]) -> list[Message]:
    """Keep every id, but only user-written text is indexable."""
    return [replace(m, content=clean_text(m)) for m in messages]


def _distance_bucket(seconds: float) -> str:
    if seconds < HOUR / 6:
        return "<10m"
    if seconds < HOUR:
        return "10m-1h"
    if seconds < DAY:
        return "1h-1d"
    return ">1d"


def _overlap_bucket(query: str, target: str) -> str:
    a, b = set(query), set(target)
    if not a or not b:
        return "none"
    ratio = len(a & b) / len(b)
    return "low" if ratio < 0.2 else "mid" if ratio < 0.5 else "high"


def quote_cases(
    messages: Sequence[Message], context: int = 0, min_target_chars: int = 2, visibility: Visibility = Visibility.DEV
) -> tuple[list[RetrievalCase], Counter]:
    """Q1: find the quoted message from a reply. Returns cases and the cleaning funnel.

    The leading @mention is removed because QQ fills it in from the quote itself.
    """
    by_id = {m.msg_id: m for m in messages}
    ordered = sorted(messages, key=lambda m: (m.timestamp, m.msg_id))
    position = {m.msg_id: i for i, m in enumerate(ordered)}
    funnel: Counter = Counter()
    cases = []
    for m in ordered:
        if not m.reply_to:
            continue
        funnel["reply"] += 1
        target = by_id.get(m.reply_to)
        if target is None:
            funnel["drop_unresolved"] += 1
            continue
        if target.author == m.author:
            funnel["drop_self_quote"] += 1
            continue
        if target.timestamp >= m.timestamp:
            funnel["drop_time_order"] += 1
            continue
        if len(target.content) < min_target_chars:
            funnel["drop_target_no_text"] += 1
            continue
        text = strip_mentions(m.content)
        as_of = m.timestamp
        if context:
            # The recent messages are already on screen, so memory may only reach what precedes them.
            i = position[m.msg_id]
            before = ordered[max(0, i - context) : i]
            if any(x.msg_id == target.msg_id for x in before):
                funnel["drop_target_on_screen"] += 1
                continue
            text = " ".join([*(strip_mentions(x.content) for x in before), text]).strip()
            as_of = before[0].timestamp if before else as_of
        if not text:
            funnel["drop_query_no_text"] += 1
            continue
        if target.content in text:
            funnel["drop_query_copies_target"] += 1
            continue
        funnel["kept"] += 1
        cases.append(
            RetrievalCase(
                case_id=f"q1:{m.msg_id}",
                query=text,
                as_of=as_of,
                gold_msg_ids=frozenset({target.msg_id}),
                channel=m.channel,
                buckets={
                    "dist": _distance_bucket(m.timestamp - target.timestamp),
                    "overlap": _overlap_bucket(text, target.content),
                },
                visibility=visibility,
            )
        )
    return cases, funnel


def identity_scores(messages: Sequence[Message]) -> dict:
    """Q5: resolve a nickname at a point in time, and count wrong merges by name matching.

    Gold is the stable author id. The resolver is the option P1 baseline for nicknames:
    the most recent holder of that exact name.
    """
    holder: dict[str, str] = {}
    names_of: dict[str, set[str]] = defaultdict(set)
    seen: Counter = Counter()
    for m in sorted(messages, key=lambda x: (x.timestamp, x.msg_id)):
        nick = m.nickname_at_time
        if not nick:
            continue
        seen["mentions"] += 1
        if nick not in holder:
            seen["first_seen_name"] += 1
            if names_of[m.author]:
                seen["rename_events"] += 1
        else:
            seen["resolvable"] += 1
            if holder[nick] == m.author:
                seen["resolved_correct"] += 1
            else:
                seen["wrong_person"] += 1
        holder[nick] = m.author
        names_of[m.author].add(nick)
    owners: dict[str, set[str]] = defaultdict(set)
    for author, names in names_of.items():
        for name in names:
            owners[name].add(author)
    resolvable = seen["resolvable"]
    return {
        **seen,
        "accuracy": round(seen["resolved_correct"] / resolvable, 4) if resolvable else None,
        "people": len(names_of),
        "people_with_multiple_names": sum(len(v) > 1 for v in names_of.values()),
        "names_shared_by_people": sum(len(v) > 1 for v in owners.values()),
        # Merging by exact name wrongly joins these people; splitting by name loses these identities.
        "false_merges_if_name_is_identity": sum(len(v) - 1 for v in owners.values() if len(v) > 1),
        "split_identities_if_name_is_identity": sum(len(v) - 1 for v in names_of.values() if len(v) > 1),
    }
