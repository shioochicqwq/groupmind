"""Q9 (AUTO): can a model fill in a group's own word before and after seeing its history?"""
from __future__ import annotations

import random
import re
from collections import defaultdict
from collections.abc import Callable, Sequence

from bench.sanitize import is_sensitive
from bench.schema import Message

_CJK_RUN = re.compile(r"[㐀-鿿]{2,}")


def mine_words(
    messages: Sequence[Message], known: Callable[[str], bool], min_count: int = 5, min_speakers: int = 3
) -> list[str]:
    """Frequent 2-4 character strings outside the dictionary, used by several people (the K4 evidence rule)."""
    counts: dict[str, int] = defaultdict(int)
    speakers: dict[str, set[str]] = defaultdict(set)
    for m in messages:
        for run in _CJK_RUN.findall(m.content):
            grams = {run[i : i + n] for n in (2, 3, 4) for i in range(len(run) - n + 1)}
            for g in grams:
                counts[g] += 1
                speakers[g].add(m.author)
    words = [w for w, c in counts.items() if c >= min_count and len(speakers[w]) >= min_speakers and not known(w)]
    # Drop fragments that always occur inside a longer mined word.
    words.sort(key=lambda w: (-len(w), w))
    kept: list[str] = []
    for w in words:
        if not any(w in longer and counts[longer] >= 0.8 * counts[w] for longer in kept):
            kept.append(w)
    return sorted(kept, key=lambda w: (-counts[w], w))


def build_items(
    messages: Sequence[Message], words: Sequence[str], split_ts: float, n: int, seed: int, context: int = 5
) -> list[dict]:
    """Items come only from after split_ts; options come from the mined list, which predates it."""
    ordered = [m for m in sorted(messages, key=lambda x: (x.timestamp, x.msg_id)) if m.content]
    rng = random.Random(seed)
    by_word: dict[str, list[int]] = defaultdict(list)
    for i, m in enumerate(ordered):
        if m.timestamp < split_ts or is_sensitive(m.content):
            continue
        for w in words:
            if w in m.content:
                by_word[w].append(i)
    pool = [w for w in by_word if by_word[w]]
    rng.shuffle(pool)
    items = []
    for round_no in range(3):
        for w in pool:
            if len(items) >= n:
                return items
            if round_no >= len(by_word[w]):
                continue
            i = rng.sample(by_word[w], len(by_word[w]))[round_no]
            before = ordered[max(0, i - context) : i]
            if not before or any(w in x.content or is_sensitive(x.content) for x in before):
                continue
            target = ordered[i]
            if any(o != w and o in target.content for o in words if len(o) > len(w) and w in o):
                continue
            distractors = rng.sample([x for x in words if x != w and x not in target.content], 3)
            options = [w, *distractors]
            rng.shuffle(options)
            items.append({
                "id": f"q9:{i}",
                "word": w,
                "options": options,
                "answer": options.index(w),
                "context": before,
                "target": target,
                "masked": target.content.replace(w, "□□"),
            })
    return items


def history_examples(messages: Sequence[Message], word: str, before_ts: float, limit: int, seed: int) -> list[Message]:
    """Past uses of a word; the time filter is the leak guard for this task."""
    hits = [m for m in messages if m.timestamp < before_ts and word in m.content and not is_sensitive(m.content)]
    random.Random(seed).shuffle(hits)
    return hits[:limit]
