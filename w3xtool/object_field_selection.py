"""Canonicalize and select normalized object fields by source priority."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

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
    "aical": "display:icon",
    "gico": "display:icon",
    "gar1": "display:icon",
    "fart": "display:icon",
    "bgsc": "display:icon",
    "dfil": "display:icon",
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
    selected: dict[str, ObjectFieldValue], value: ObjectFieldValue
) -> None:
    """Mutate the materialization accumulator with the winning field value."""
    identity = _field_identity(value)
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
                    existing.source_kind is ObjectSourceKind.BASE
                    and existing.label.casefold() == label
                ):
                    del selected[existing_identity]
    previous = selected.get(identity)
    if previous is None or _field_rank(value, identity) > _field_rank(
        previous, identity
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


def object_field_source_priority(value: ObjectFieldValue) -> int:
    """Return the effective priority used by public-field selection."""
    identity = _field_identity(value)
    if value.source_kind is ObjectSourceKind.TEXT_STRINGS and not identity.startswith(
        "display:"
    ):
        return 15
    return int(value.source_kind)


def _field_identity(value: ObjectFieldValue) -> str:
    key = value.key.casefold()
    alias = _DISPLAY_ALIASES.get(key)
    if alias is None and key.startswith("display:"):
        alias = key
    non_display_key = key.removeprefix("binary:")
    if alias is not None:
        return alias
    if value.source_kind is ObjectSourceKind.BASE:
        return _BASE_LABEL_ALIASES.get(
            value.label.casefold(), f"base:{value.label.casefold()}"
        )
    semantic_alias = _NON_DISPLAY_ALIASES.get(non_display_key)
    raw_key = value.key[len("binary:") :] if key.startswith("binary:") else value.key
    return semantic_alias or f"field:{raw_key}"


def _field_rank(
    value: ObjectFieldValue,
    identity: str,
) -> tuple[int, str, str, str, str, str, str, str, str]:
    normalized_source = value.source.replace("/", "\\")
    return (
        object_field_source_priority(value),
        normalized_source.casefold(),
        normalized_source,
        value.source,
        value.key.casefold(),
        value.key,
        value.label.casefold(),
        value.label,
        value.value,
    )
