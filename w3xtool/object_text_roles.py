"""Classify Warcraft object fields into complete-text semantic roles."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class TextRoleMatch:
    """Semantic text role plus its explicit level or variant."""

    role: str
    level: int | None


_LEVEL_IN_LABEL: Final = re.compile(
    r"(?:等级|level)\s*[:：]?\s*(\d+)",
    re.IGNORECASE,
)
_TRAILING_LEVEL_KEY: Final = re.compile(r"^(?:gtp|gub)(\d+)$", re.IGNORECASE)
_NAME_KEYS: Final = frozenset(
    {"name", "unam", "anam", "gnam", "bnam", "dnam", "fnam", "display:name"},
)
_PROPER_NAME_KEYS: Final = frozenset({"propernames", "upro", "display:propernames"})
_SUFFIX_KEYS: Final = frozenset(
    {"editorsuffix", "unsf", "ansf", "gnsf", "bnsf", "dnsf", "fnsf"},
)
_BASE_TIP_KEYS: Final = frozenset(
    {"tip", "utip", "atp1", "display:tip"},
)
_EXTENDED_TIP_KEYS: Final = frozenset(
    {"ubertip", "utub", "aub1", "display:description"},
)
_LEARN_TIP_KEYS: Final = frozenset({"aret", "researchtip"})
_LEARN_EXTENDED_KEYS: Final = frozenset({"arut", "researchubertip"})
_CLOSE_TIP_KEYS: Final = frozenset({"aut1", "untip"})
_CLOSE_EXTENDED_KEYS: Final = frozenset({"auu1", "unubertip"})
_EDITOR_DESCRIPTION_KEYS: Final = frozenset({"ides", "description", "editordescription"})


def classify_text_field(category: str, key: str, label: str) -> TextRoleMatch | None:
    """Return the requested semantic role for one known text-bearing field."""
    normalized_key, level = _key_and_level(key, label)
    normalized_label = _normalize_label(label)

    if normalized_key in _NAME_KEYS:
        return TextRoleMatch("名称", level)
    if normalized_key in _PROPER_NAME_KEYS or "称谓" in normalized_label:
        return TextRoleMatch("称谓", level)
    if normalized_key in _SUFFIX_KEYS or "编辑器后缀" in normalized_label:
        return TextRoleMatch("编辑器后缀", level)
    if normalized_key in {"revivetip", "reviveubertip"} or "复活" in normalized_label:
        return TextRoleMatch("复活提示", level)
    if normalized_key in {"awakentip", "awakenubertip"} or "唤醒" in normalized_label:
        return TextRoleMatch("唤醒提示", level)
    if normalized_key in _LEARN_EXTENDED_KEYS or _is_learn_extended(normalized_label):
        return TextRoleMatch("学习扩展提示", level)
    if normalized_key in _LEARN_TIP_KEYS or _is_learn_tip(normalized_label):
        return TextRoleMatch("学习提示", level)
    if normalized_key in _CLOSE_EXTENDED_KEYS or _is_close_extended(normalized_label):
        return TextRoleMatch("关闭扩展提示", level)
    if normalized_key in _CLOSE_TIP_KEYS or _is_close_tip(normalized_label):
        return TextRoleMatch("关闭提示", level)
    if category.casefold() in {"增益", "buff", "效果"}:
        if normalized_key in {"fube", "ubertip"} or _is_extended(normalized_label):
            return TextRoleMatch("Buff扩展提示", level)
        if normalized_key in {"ftip", "tip"} or _is_tooltip(normalized_label):
            return TextRoleMatch("Buff提示", level)
    if normalized_key in _EDITOR_DESCRIPTION_KEYS or "编辑器描述" in normalized_label:
        return TextRoleMatch("编辑器描述", level)
    if normalized_key.startswith("gub") or normalized_key in _EXTENDED_TIP_KEYS:
        return TextRoleMatch("扩展提示", level)
    if normalized_key.startswith("gtp") or normalized_key in _BASE_TIP_KEYS:
        return TextRoleMatch("基础提示", level)
    return None


def _key_and_level(key: str, label: str) -> tuple[str, int | None]:
    normalized = key.casefold().removeprefix("binary:").removeprefix("field:")
    base, separator, suffix = normalized.rpartition(":")
    if separator and suffix.isdecimal():
        return base, int(suffix)
    label_level = _LEVEL_IN_LABEL.search(label)
    if label_level is not None:
        return normalized, int(label_level.group(1))
    trailing = _TRAILING_LEVEL_KEY.fullmatch(normalized)
    if trailing is not None:
        return normalized, int(trailing.group(1))
    return normalized, None


def _normalize_label(label: str) -> str:
    return "".join(label.casefold().split())


def _is_extended(label: str) -> bool:
    return "扩展" in label or "uber" in label


def _is_tooltip(label: str) -> bool:
    return "提示" in label or "tooltip" in label


def _is_learn_extended(label: str) -> bool:
    return ("学习" in label or "research" in label) and _is_extended(label)


def _is_learn_tip(label: str) -> bool:
    return ("学习" in label or "research" in label) and not _is_extended(label)


def _is_close_extended(label: str) -> bool:
    return ("关闭" in label or "close" in label or "off" in label) and _is_extended(label)


def _is_close_tip(label: str) -> bool:
    return (
        ("关闭" in label or "close" in label or "off" in label)
        and not _is_extended(label)
        and "按钮位置" not in label
    )
