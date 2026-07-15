"""Classify exact Warcraft icon fields without presentation-label inference."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, assert_never

from .object_candidates import ObjectSourceKind


class IconFieldDisposition(StrEnum):
    """Closed outcomes for one candidate icon field."""

    ELIGIBLE = "eligible"
    FILTERED_NON_ICON = "filtered_non_icon_field"
    NOT_AN_ICON_FIELD = "not_an_icon_field"


@dataclass(frozen=True, slots=True)
class IconFieldDecision:
    """Eligibility outcome and the normalized field key supporting it."""

    disposition: IconFieldDisposition
    canonical_key: str
    detail: str = ""


_KNOWN_KEYS: Final[Mapping[str, frozenset[str]]] = {
    "单位": frozenset(("uico",)),
    "物品": frozenset(("iico",)),
    "技能": frozenset(("aart", "art")),
    "科技": frozenset(("gar1",)),
    "增益": frozenset(("fart",)),
    "效果": frozenset(("fart",)),
}
_LEGACY_FALSE_ALIASES: Final = frozenset(
    ("aical", "bgsc", "dfil", "gico", "researchart")
)
_FILTERED_VALUE_TYPES: Final = frozenset(("model", "real"))


def classify_icon_field(
    category: str,
    key: str,
    label: str,
    value_type: str,
    source_kind: ObjectSourceKind,
) -> IconFieldDecision:
    """Return the exact icon eligibility decision for one object field."""
    _ = label
    canonical_key = key.casefold().removeprefix("binary:").removeprefix("field:")
    base_key, separator, level = canonical_key.rpartition(":")
    if separator and level.isdecimal():
        canonical_key = base_key
    normalized_type = value_type.casefold()
    if (
        normalized_type in _FILTERED_VALUE_TYPES
        or canonical_key in _LEGACY_FALSE_ALIASES
    ):
        return IconFieldDecision(
            IconFieldDisposition.FILTERED_NON_ICON,
            canonical_key,
        )

    match source_kind:
        case ObjectSourceKind.BASE:
            is_bundled_base = True
        case (
            ObjectSourceKind.TEXT_ANONYMOUS
            | ObjectSourceKind.SLK
            | ObjectSourceKind.TEXT_FUNC
            | ObjectSourceKind.BINARY
            | ObjectSourceKind.TEXT_STRINGS
        ):
            is_bundled_base = False
        case unreachable:
            assert_never(unreachable)

    if canonical_key == "base:图标":
        disposition = (
            IconFieldDisposition.ELIGIBLE
            if is_bundled_base
            else IconFieldDisposition.NOT_AN_ICON_FIELD
        )
        return IconFieldDecision(disposition, canonical_key)
    if is_bundled_base:
        return IconFieldDecision(
            IconFieldDisposition.NOT_AN_ICON_FIELD,
            canonical_key,
        )
    category_keys = _KNOWN_KEYS.get(category.casefold())
    if category_keys is not None and (
        canonical_key in category_keys or normalized_type == "icon"
    ):
        return IconFieldDecision(IconFieldDisposition.ELIGIBLE, canonical_key)
    return IconFieldDecision(IconFieldDisposition.NOT_AN_ICON_FIELD, canonical_key)
