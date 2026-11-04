"""Filter applied before any real message leaves this machine.

Stable pseudonyms replace people; contact details and identifiers are masked; messages
that mention highly sensitive subjects are withheld from model calls.
"""
from __future__ import annotations

import re
from collections.abc import Iterable

from bench.schema import Message

_PLACEHOLDER = re.compile(r"\[(?:图片|动画表情|语音|视频|文件|聊天记录|小程序|按钮|头像)[^\]]*\]")
_URL = re.compile(r"https?://\S+|www\.\S+", re.I)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_ID_CARD = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
_BANK = re.compile(r"(?<!\d)\d{16,19}(?!\d)")
_PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_LONG_NUM = re.compile(r"(?<!\d)\d{6,15}(?!\d)")
_AT = re.compile(r"@\S+")

# Withheld entirely: the user has not set rules yet, so this errs on the side of not sending.
SENSITIVE_TERMS = (
    "身份证", "银行卡", "信用卡", "密码", "验证码", "住址", "家庭地址", "手机号", "电话号码", "病历", "诊断",
    "抑郁", "自杀", "自残", "堕胎", "怀孕", "性侵", "裸照", "工资", "欠款", "贷款", "支付宝", "微信号",
    "api key", "apikey", "token", "secret",
)

# Message types without user-written text: system notices, recalls, bot buttons.
NON_TEXT_TYPES = {"80", "81", "99"}


def is_sensitive(text: str) -> bool:
    low = text.lower()
    return any(term in low for term in SENSITIVE_TERMS) or bool(_ID_CARD.search(text) or _BANK.search(text))


def clean_text(message: Message) -> str:
    """User-written text only, with media placeholders removed."""
    if message.media and message.media[0] in NON_TEXT_TYPES:
        return ""
    return _PLACEHOLDER.sub("", message.content).strip()


def strip_mentions(text: str) -> str:
    return _AT.sub("", text).strip()


class Sanitizer:
    def __init__(self, messages: Iterable[Message]):
        self.alias: dict[str, str] = {}
        nick_owner: dict[str, str] = {}
        for m in messages:
            self.alias.setdefault(m.author, f"P{len(self.alias) + 1:03d}")
            if len(m.nickname_at_time) >= 2:
                nick_owner[m.nickname_at_time] = m.author
        self.nick_alias = sorted(
            ((nick, self.alias[owner]) for nick, owner in nick_owner.items()), key=lambda kv: -len(kv[0])
        )

    def author(self, message: Message) -> str:
        return self.alias[message.author]

    def text(self, raw: str) -> str:
        out = raw
        for nick, alias in self.nick_alias:
            if nick in out:
                out = out.replace(nick, alias)
        out = _URL.sub("<URL>", out)
        out = _EMAIL.sub("<EMAIL>", out)
        out = _ID_CARD.sub("<ID>", out)
        out = _BANK.sub("<NUM>", out)
        out = _PHONE.sub("<PHONE>", out)
        out = _LONG_NUM.sub("<NUM>", out)
        return out
