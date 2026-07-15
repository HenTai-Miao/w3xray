"""Shared strict schema primitives for trusted description caches."""

from __future__ import annotations

import re
from typing import Final


DIGEST: Final = re.compile(r"[0-9a-f]{64}")
PLACEHOLDERS: Final = frozenset({"", "-", "_", ",", '""', "''"})
CACHE_HEADER: Final = (
    "分类",
    "基础ID",
    "文本角色",
    "等级/变体",
    "原始全文",
    "可读全文",
    "来源地图SHA256",
    "来源清单SHA256",
    "来源路径",
)


def parse_level(value: str) -> int | None:
    """Parse an optional nonnegative decimal level."""
    stripped = value.strip()
    return int(stripped) if stripped.isdecimal() else None


def is_placeholder(value: str) -> bool:
    """Return whether a text value is an explicit non-description placeholder."""
    return value.strip() in PLACEHOLDERS


def is_yes(value: str) -> bool:
    """Parse the report's canonical and legacy affirmative spellings."""
    return value.strip().casefold() in {"是", "true", "1", "yes"}


def is_digest(value: str) -> bool:
    """Accept only canonical lowercase SHA-256 text."""
    return DIGEST.fullmatch(value) is not None
