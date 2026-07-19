"""Canonicalize and select normalized object fields by source priority."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Final, assert_never

from .icon_field_evidence import (
    IconFieldDisposition,
    classify_icon_field,
    icon_display_priority,
)
from .object_candidates import ObjectFieldValue, ObjectSourceKind

_DISPLAY_ALIASES: Final[Mapping[str, str]] = {
    "name": "display:name",
    "unam": "display:name",
    "anam": "display:name",
    "gnam": "display:name",
    "bnam": "display:name",
    "dnam": "display:name",
    "fnam": "display:name",
    "propernames": "display:propernames",
    "tip": "display:tip",
    "ubertip": "display:description",
    "description": "display:description",
    "icon": "display:icon",
    "art": "display:icon",
    "ico": "display:icon",
    "uico": "display:icon",
    "iico": "display:icon",
    "aart": "display:icon",
    "gar1": "display:icon",
    "fart": "display:icon",
}
_NON_DISPLAY_ALIASES: Final[Mapping[str, str]] = {
    "hp": "field:unit:hit-points",
    "hitpoints": "field:unit:hit-points",
    "uhpm": "field:unit:hit-points",
}
_BASE_LABEL_ALIASES: Final[Mapping[str, str]] = {
    "名称": "display:name",
    "名字": "display:propernames",
    "提示": "display:tip",
    "说明": "display:description",
    "图标": "display:icon",
    "生命": "field:unit:hit-points",
    "生命上限": "field:unit:hit-points",
}


def select_object_field(
    selected: dict[str, ObjectFieldValue],
    value: ObjectFieldValue,
    category: str,
) -> None:
    """Mutate the materialization accumulator with the winning field value."""
    identity = _field_identity(value, category)
    if not identity.startswith("display:"):
        label = value.label.casefold()
        if value.source_kind is ObjectSourceKind.BASE:
            if any(
                existing.source_kind is not ObjectSourceKind.BASE
                and existing.label.casefold() == label
                for existing in selected.values()
            ):
                return
        else:
            for existing_identity, existing in tuple(selected.items()):
                if (
                    existing_identity != "display:icon"
                    and existing.source_kind is ObjectSourceKind.BASE
                    and existing.label.casefold() == label
                ):
                    del selected[existing_identity]
    previous = selected.get(identity)
    if previous is None or _field_rank(value, identity, category) > _field_rank(
        previous,
        identity,
        category,
    ):
        selected[identity] = value


def public_object_field_key(identity: str, value: ObjectFieldValue) -> str:
    """Return the stable public key for one selected field."""
    return identity if identity.startswith("display:") else value.key


def selected_display_value(
    selected: Mapping[str, ObjectFieldValue], identity: str
) -> str:
    """Return one canonical display value or an empty string when absent."""
    value = selected.get(identity)
    return "" if value is None else value.value


def select_current_icon_fields(
    values: Iterable[ObjectFieldValue],
    category: str,
) -> tuple[ObjectFieldValue, ...]:
    """Select one current value for the primary and each auxiliary icon role."""
    selected: dict[str, ObjectFieldValue] = {}
    for value in values:
        decision = classify_icon_field(
            category,
            value.key,
            value.label,
            value.value_type,
            value.source_kind,
        )
        if decision.disposition is not IconFieldDisposition.ELIGIBLE:
            continue
        role = (
            "display:icon"
            if icon_display_priority(category, value.key, value.source_kind) > 1
            else f"icon:{decision.canonical_key}"
        )
        previous = selected.get(role)
        if previous is None or _field_rank(value, role, category) > _field_rank(
            previous,
            role,
            category,
        ):
            selected[role] = value
    return tuple(selected[role] for role in sorted(selected))


def object_field_source_priority(value: ObjectFieldValue, category: str) -> int:
    """Return the effective priority used by public-field selection."""
    identity = _field_identity(value, category)
    if value.source_kind is ObjectSourceKind.TEXT_STRINGS and not identity.startswith(
        "display:"
    ):
        return 15
    return int(value.source_kind)


def _field_identity(value: ObjectFieldValue, category: str) -> str:
    key = value.key.casefold()
    decision = classify_icon_field(
        category,
        value.key,
        value.label,
        value.value_type,
        value.source_kind,
    )
    match decision.disposition:
        case IconFieldDisposition.ELIGIBLE:
            return "display:icon"
        case (
            IconFieldDisposition.FILTERED_NON_ICON
            | IconFieldDisposition.NOT_AN_ICON_FIELD
        ):
            pass
        case unreachable:
            assert_never(unreachable)
    alias = _DISPLAY_ALIASES.get(key)
    if alias == "display:icon":
        alias = None
    if alias is None and key.startswith("display:") and key != "display:icon":
        alias = key
    non_display_key = key.removeprefix("binary:")
    if alias is not None:
        return alias
    if value.source_kind is ObjectSourceKind.BASE:
        base_alias = _BASE_LABEL_ALIASES.get(value.label.casefold())
        if base_alias == "display:icon":
            base_alias = None
        return base_alias or f"base:{value.label.casefold()}"
    semantic_alias = _NON_DISPLAY_ALIASES.get(non_display_key)
    raw_key = value.key[len("binary:") :] if key.startswith("binary:") else value.key
    return semantic_alias or f"field:{raw_key}"


def _field_rank(
    value: ObjectFieldValue,
    identity: str,
    category: str,
) -> tuple[int, int, str, str, str, str, str, str, str, str]:
    normalized_source = value.source.replace("/", "\\")
    display_priority = (
        icon_display_priority(category, value.key, value.source_kind)
        if identity == "display:icon"
        else 0
    )
    return (
        display_priority,
        object_field_source_priority(value, category),
        normalized_source.casefold(),
        normalized_source,
        value.source,
        value.key.casefold(),
        value.key,
        value.label.casefold(),
        value.label,
        value.value,
    )
