"""Tokenizers compared by option I1. All return lowercase tokens."""
from __future__ import annotations

import re
from collections.abc import Callable

_WORD_RE = re.compile(r"[A-Za-z0-9_]+")
_CJK_RE = re.compile(r"[㐀-鿿]+")
_MIXED_RE = re.compile(r"[A-Za-z0-9_]+|[㐀-鿿]")


def word(text: str) -> list[str]:
    """GroupMemBench's own tokenizer: ASCII words only."""
    return [t.lower() for t in _WORD_RE.findall(text)]


def bigram(text: str) -> list[str]:
    tokens = [t.lower() for t in _WORD_RE.findall(text)]
    for run in _CJK_RE.findall(text):
        tokens.extend(run if len(run) == 1 else (run[i : i + 2] for i in range(len(run) - 1)))
    return tokens


def unigram(text: str) -> list[str]:
    return [t.lower() for t in _MIXED_RE.findall(text)]


def make_jieba(learned_words: tuple[str, ...] = ()) -> Callable[[str], list[str]]:
    import jieba

    jieba.setLogLevel(60)
    tk = jieba.Tokenizer()
    for w in learned_words:
        tk.add_word(w, freq=1000)

    def tokenize(text: str) -> list[str]:
        return [t.lower() for t in tk.lcut(text) if _MIXED_RE.search(t)]

    return tokenize


def get(name: str) -> Callable[[str], list[str]]:
    if name == "jieba":
        return make_jieba()
    return {"word": word, "bigram": bigram, "unigram": unigram}[name]
