"""Canonicalize and select normalized object fields by source priority."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from functools import lru_cache
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


@dataclass(slots=True)
class SelectionIndex:
    """select_object_field 的标签加速索引，须与 ``selected`` 同步维护。

    物化一个对象原本要对每个字段全量扫已选条目做标签优先级判定，
    字段多的对象是平方级；这里按 casefold 标签维护非 BASE 计数和
    BASE 条目映射，判定降为常数时间。不带索引调用时回退到原扫描。
    """

    non_base_counts: dict[str, int] = field(default_factory=dict)
    base_entries: dict[str, dict[str, ObjectFieldValue]] = field(default_factory=dict)


def build_selection_index() -> SelectionIndex:
    """Return one fresh accelerator index for a materialization accumulator."""
    return SelectionIndex()


def select_object_field(
    selected: dict[str, ObjectFieldValue],
    value: ObjectFieldValue,
    category: str,
    index: SelectionIndex | None = None,
) -> None:
    """Mutate the materialization accumulator with the winning field value."""
    identity = _field_identity(value, category)
    if not identity.startswith("display:"):
        label = value.label.casefold()
        if value.source_kind is ObjectSourceKind.BASE:
            if _blocked_by_non_base_label(selected, label, index):
                return
        else:
            _remove_base_labeled(selected, label, index)
    previous = selected.get(identity)
    if previous is None or _field_rank(value, identity, category) > _field_rank(
        previous,
        identity,
        category,
    ):
        _store_selected(selected, identity, value, index)


def _blocked_by_non_base_label(
    selected: Mapping[str, ObjectFieldValue],
    label: str,
    index: SelectionIndex | None,
) -> bool:
    if index is not None:
        return index.non_base_counts.get(label, 0) > 0
    return any(
        existing.source_kind is not ObjectSourceKind.BASE
        and existing.label.casefold() == label
        for existing in selected.values()
    )


def _remove_base_labeled(
    selected: dict[str, ObjectFieldValue],
    label: str,
    index: SelectionIndex | None,
) -> None:
    if index is not None:
        entries = index.base_entries.get(label)
        if not entries:
            return
        for identity in tuple(entries):
            if identity == "display:icon":
                continue
            del selected[identity]
            del entries[identity]
        if not entries:
            del index.base_entries[label]
        return
    for existing_identity, existing in tuple(selected.items()):
        if (
            existing_identity != "display:icon"
            and existing.source_kind is ObjectSourceKind.BASE
            and existing.label.casefold() == label
        ):
            del selected[existing_identity]


def _store_selected(
    selected: dict[str, ObjectFieldValue],
    identity: str,
    value: ObjectFieldValue,
    index: SelectionIndex | None,
) -> None:
    previous = selected.get(identity)
    if previous is not None and index is not None:
        _unregister_selected(index, identity, previous)
    selected[identity] = value
    if index is not None:
        _register_selected(index, identity, value)


def _register_selected(
    index: SelectionIndex,
    identity: str,
    value: ObjectFieldValue,
) -> None:
    label = value.label.casefold()
    if value.source_kind is ObjectSourceKind.BASE:
        index.base_entries.setdefault(label, {})[identity] = value
    else:
        index.non_base_counts[label] = index.non_base_counts.get(label, 0) + 1


def _unregister_selected(
    index: SelectionIndex,
    identity: str,
    previous: ObjectFieldValue,
) -> None:
    label = previous.label.casefold()
    if previous.source_kind is ObjectSourceKind.BASE:
        entries = index.base_entries.get(label)
        if entries is not None:
            entries.pop(identity, None)
            if not entries:
                del index.base_entries[label]
        return
    remaining = index.non_base_counts.get(label, 0) - 1
    if remaining > 0:
        index.non_base_counts[label] = remaining
    else:
        index.non_base_counts.pop(label, None)


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


@lru_cache(maxsize=131_072)
def _field_identity(value: ObjectFieldValue, category: str) -> str:
    """Return the canonical public identity for one field value.

    纯函数；select_object_field 与 _field_rank 会对同一值各算一次，
    物化大地图时这里是百万级调用，记忆化后按不同值收敛。
    """
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
