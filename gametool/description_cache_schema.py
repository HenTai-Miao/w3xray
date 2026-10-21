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
LEGACY_CACHE_HEADER: Final = (
    "分类",
    "基础ID",
    "文本角色",
    "等级/变体",
    "原始全文",
    "可读全文",
    "来源地图SHA256",
    "来源路径",
)
LEGACY_DESCRIPTION_HEADER: Final = (
    "分类",
    "对象ID",
    "基础ID",
    "名称",
    "自定义",
    "等级",
    "原始提示",
    "可读提示",
    "提示来源",
    "原始说明",
    "可读说明",
    "说明来源",
    "完整性状态",
)
DESCRIPTION_CACHE_SOURCE_HEADER: Final = (
    "分类",
    "基础ID",
    "文本角色",
    "等级/变体",
    "来源地图SHA256",
    "来源报告路径",
    "来源报告SHA256",
    "来源行号",
    "来源行SHA256",
    "来源标签",
)
DESCRIPTION_CACHE_REJECTION_HEADER: Final = (
    *LEGACY_CACHE_HEADER,
    "拒绝原因",
    "详情",
    "候选行号",
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
