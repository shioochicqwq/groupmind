"""Unified message and evaluation records shared by public and real datasets."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Visibility(str, Enum):
    DEV = "DEV"
    VALIDATION = "VALIDATION"
    FROZEN = "FROZEN"


class LabelAuthority(str, Enum):
    AUTO = "AUTO"
    SILVER = "SILVER"
    GOLD = "GOLD"


@dataclass(frozen=True)
class Message:
    msg_id: str
    channel: str
    author: str
    timestamp: float
    content: str
    reply_to: str | None = None
    media: tuple[str, ...] = ()
    nickname_at_time: str = ""


@dataclass(frozen=True)
class Block:
    """A retrievable unit: ordered raw messages plus the text the index sees."""

    block_id: str
    msg_ids: tuple[str, ...]
    end_ts: float
    channel: str
    index_text: str
    labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class RetrievalCase:
    case_id: str
    query: str
    as_of: float
    gold_msg_ids: frozenset[str]
    channel: str = ""
    buckets: dict[str, str] = field(default_factory=dict)
    visibility: Visibility = Visibility.DEV
    label_authority: LabelAuthority = LabelAuthority.AUTO


class HoldoutViolation(RuntimeError):
    """Raised when non-DEV data would reach tuning code."""


def require_dev(visibility: Visibility, allow_holdout: bool = False) -> None:
    if visibility is not Visibility.DEV and not allow_holdout:
        raise HoldoutViolation(f"{visibility.value} data needs an explicit holdout run")
