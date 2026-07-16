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
    semantic_field: str


_LEVEL_IN_LABEL: Final = re.compile(
    r"[\(（]?\s*(?:等级|level)\s*[:：]?\s*(\d+)\s*[\)）]?",
    re.IGNORECASE,
)
_TRAILING_LEVEL_KEY: Final = re.compile(r"^(gtp|gub)(\d+)$", re.IGNORECASE)
_SEMANTIC_FIELDS: Final = {
    **{
        key: ("名称", "name")
        for key in (
            "name",
            "unam",
            "anam",
            "gnam",
            "bnam",
            "dnam",
            "fnam",
            "display:name",
        )
    },
    **{
        key: ("称谓", "propernames")
        for key in ("propernames", "upro", "display:propernames")
    },
    **{
        key: ("编辑器后缀", "editorsuffix")
        for key in ("editorsuffix", "unsf", "ansf", "gnsf", "bnsf", "dnsf", "fnsf")
    },
    **{key: ("基础提示", "tip") for key in ("tip", "utip", "atp1", "display:tip")},
    **{
        key: ("扩展提示", "ubertip")
        for key in ("ubertip", "utub", "aub1", "display:description")
    },
    **{key: ("学习提示", "researchtip") for key in ("researchtip", "aret")},
    **{key: ("学习扩展提示", "researchubertip") for key in ("researchubertip", "arut")},
    **{key: ("关闭提示", "untip") for key in ("untip", "aut1")},
    **{key: ("关闭扩展提示", "unubertip") for key in ("unubertip", "auu1")},
    "revivetip": ("复活提示", "revivetip"),
    "reviveubertip": ("复活提示", "reviveubertip"),
    "awakentip": ("唤醒提示", "awakentip"),
    "awakenubertip": ("唤醒提示", "awakenubertip"),
    **{
        key: ("编辑器描述", "editordescription")
        for key in ("ides", "description", "editordescription")
    },
}
_LABEL_FIELDS: Final = {
    "名称": ("名称", "name"),
    "称谓": ("称谓", "propernames"),
    "编辑器后缀": ("编辑器后缀", "editorsuffix"),
    "提示工具-基础": ("基础提示", "tip"),
    "提示工具-普通": ("基础提示", "tip"),
    "提示工具-扩展": ("扩展提示", "ubertip"),
    "提示工具-扩展的": ("扩展提示", "ubertip"),
    "提示工具-学习": ("学习提示", "researchtip"),
    "提示工具-学习-扩展": ("学习扩展提示", "researchubertip"),
    "提示工具-学习-扩展的": ("学习扩展提示", "researchubertip"),
    "提示工具-关闭": ("关闭提示", "untip"),
    "提示工具-关闭-扩展": ("关闭扩展提示", "unubertip"),
    "提示工具-关闭-扩展的": ("关闭扩展提示", "unubertip"),
    "提示工具-复活": ("复活提示", "revivetip"),
    "提示工具-复活-扩展的": ("复活提示", "reviveubertip"),
    "提示工具-唤醒": ("唤醒提示", "awakentip"),
    "提示工具-唤醒-扩展的": ("唤醒提示", "awakenubertip"),
    "描述": ("编辑器描述", "editordescription"),
    "编辑器描述": ("编辑器描述", "editordescription"),
}
_BUFF_FIELDS: Final = {
    "ftip": ("Buff提示", "tip"),
    "tip": ("Buff提示", "tip"),
    "fube": ("Buff扩展提示", "ubertip"),
    "ubertip": ("Buff扩展提示", "ubertip"),
}
_BUFF_LABEL_FIELDS: Final = {
    "工具提示": ("Buff提示", "tip"),
    "工具提示-扩展": ("Buff扩展提示", "ubertip"),
    "工具提示-扩展的": ("Buff扩展提示", "ubertip"),
}
_ROLE_SEMANTIC_FIELDS: Final = {
    "名称": "name",
    "称谓": "propernames",
    "编辑器后缀": "editorsuffix",
    "基础提示": "tip",
    "扩展提示": "ubertip",
    "学习提示": "researchtip",
    "学习扩展提示": "researchubertip",
    "关闭提示": "untip",
    "关闭扩展提示": "unubertip",
    "复活提示": "revivetip",
    "唤醒提示": "awakentip",
    "编辑器描述": "editordescription",
    "Buff提示": "tip",
    "Buff扩展提示": "ubertip",
}


def semantic_field_for_role(role: str) -> str:
    """Return the one canonical field a role-only cache row can identify."""
    return _ROLE_SEMANTIC_FIELDS.get(role, role.casefold())


def classify_text_field(
    category: str,
    key: str,
    label: str,
    value_type: str = "",
) -> TextRoleMatch | None:
    """Return the requested semantic role for one known text-bearing field."""
    normalized_key, level = _key_and_level(key, label)
    normalized_label = _normalize_label(label)
    matched = None
    if category.casefold() in {"增益", "buff", "效果"}:
        matched = _BUFF_FIELDS.get(normalized_key) or _BUFF_LABEL_FIELDS.get(
            normalized_label
        )
    if matched is None:
        matched = _SEMANTIC_FIELDS.get(normalized_key) or _LABEL_FIELDS.get(
            normalized_label
        )
    if matched is None:
        trailing = _TRAILING_LEVEL_KEY.fullmatch(normalized_key)
        if trailing is not None:
            matched = (
                ("基础提示", "tip")
                if trailing.group(1).casefold() == "gtp"
                else ("扩展提示", "ubertip")
            )
    if matched is not None:
        return TextRoleMatch(matched[0], level, matched[1])
    if value_type.casefold() == "string":
        return TextRoleMatch(normalized_key, level, normalized_key)
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
        return normalized, int(trailing.group(2))
    return normalized, None


def _normalize_label(label: str) -> str:
    without_level = _LEVEL_IN_LABEL.sub("", label).strip().rstrip("-:：(（")
    return "".join(without_level.casefold().split())
