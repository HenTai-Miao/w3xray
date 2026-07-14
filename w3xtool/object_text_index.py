"""Resolve lossless map, client, and trusted-cache object text."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from .description_cache import DescriptionCache
from .object_candidates import ObjectCandidate
from .object_text_evidence import (
    TextEvidence,
    TextIdentity,
    cache_text_evidence,
    collect_client_text_evidence,
    collect_map_text_evidence,
    readable_text,
    synthetic_text_evidence,
    unique_text_evidence,
)
from .object_text_models import ObjectTextIndex, ObjectTextRecord, ObjectTextState

if TYPE_CHECKING:
    from .client_object_data import ClientBaseObject
    from .map_data import GameObject


_EXPECTED_ROLES: Final = {
    "单位": ("基础提示", "扩展提示", "复活提示", "唤醒提示", "编辑器描述"),
    "物品": ("基础提示", "扩展提示", "编辑器描述"),
    "技能": (
        "基础提示",
        "扩展提示",
        "学习提示",
        "学习扩展提示",
        "关闭提示",
        "关闭扩展提示",
    ),
    "科技": ("基础提示", "扩展提示"),
    "增益": ("Buff提示", "Buff扩展提示", "编辑器描述"),
    "可破坏物": ("编辑器描述",),
    "装饰物": ("编辑器描述",),
}


@dataclass(frozen=True, slots=True)
class _ResolvedEvidence:
    evidence: TextEvidence
    state: ObjectTextState
    conflict_group: str


def build_object_text_index(
    objects: Iterable[GameObject],
    map_candidates: Iterable[ObjectCandidate],
    client_objects: Iterable[ClientBaseObject],
    cache: DescriptionCache,
    *,
    client_text_available: bool,
) -> ObjectTextIndex:
    """Resolve every expected role with strict source precedence."""
    object_rows = tuple(
        sorted(objects, key=lambda item: (item.category.casefold(), item.obj_id))
    )
    map_evidence = collect_map_text_evidence(tuple(map_candidates))
    client_evidence = collect_client_text_evidence(tuple(client_objects))
    map_roles = _role_index(map_evidence)
    client_roles = _role_index(client_evidence)
    cache_roles = _cache_role_index(cache)
    resolved: list[tuple[GameObject, _ResolvedEvidence]] = []
    for item in object_rows:
        identities = _identities_for_object(item, map_roles, client_roles, cache_roles)
        for role, level in identities:
            key = (item.category, item.obj_id, role, level)
            base_key = (item.category, item.base_id, role, level)
            evidence = _resolve_evidence(
                key,
                map_evidence.get(key, ()),
                client_evidence.get(base_key, ()),
                cache_text_evidence(cache, base_key),
                client_text_available,
            )
            resolved.extend((item, row) for row in evidence)
    ordered = tuple(sorted(resolved, key=_resolved_sort_key))
    records = tuple(
        _to_record(item, row, ordinal) for ordinal, (item, row) in enumerate(ordered, 1)
    )
    return ObjectTextIndex.build(records)


def _identities_for_object(
    item: GameObject,
    map_roles: dict[tuple[str, str], set[tuple[str, int | None]]],
    client_roles: dict[tuple[str, str], set[tuple[str, int | None]]],
    cache_roles: dict[tuple[str, str], set[tuple[str, int | None]]],
) -> tuple[tuple[str, int | None], ...]:
    identities: set[tuple[str, int | None]] = {
        (role, None) for role in _EXPECTED_ROLES.get(item.category, ())
    }
    identities.update(map_roles.get((item.category, item.obj_id), ()))
    identities.update(client_roles.get((item.category, item.base_id), ()))
    identities.update(cache_roles.get((item.category, item.base_id), ()))
    return tuple(
        sorted(
            identities,
            key=lambda value: (
                value[0].casefold(),
                -1 if value[1] is None else value[1],
            ),
        )
    )


def _role_index(
    evidence: dict[TextIdentity, tuple[TextEvidence, ...]],
) -> dict[tuple[str, str], set[tuple[str, int | None]]]:
    indexed: dict[tuple[str, str], set[tuple[str, int | None]]] = {}
    for category, object_id, role, level in evidence:
        indexed.setdefault((category, object_id), set()).add((role, level))
    return indexed


def _cache_role_index(
    cache: DescriptionCache,
) -> dict[tuple[str, str], set[tuple[str, int | None]]]:
    indexed: dict[tuple[str, str], set[tuple[str, int | None]]] = {}
    for entry in cache.entries:
        indexed.setdefault((entry.category, entry.base_id), set()).add(
            (entry.role, entry.level)
        )
    return indexed


def _resolve_evidence(
    identity: TextIdentity,
    map_values: tuple[TextEvidence, ...],
    client_values: tuple[TextEvidence, ...],
    cache_values: tuple[TextEvidence, ...],
    client_text_available: bool,
) -> tuple[_ResolvedEvidence, ...]:
    named = tuple(row for row in map_values if row.source_kind != "地图匿名文本块")
    anonymous = tuple(row for row in map_values if row.source_kind == "地图匿名文本块")
    state, selected = _select_map_tier(named)
    if state is None:
        state, selected = _select_map_tier(anonymous)
    if state is None:
        state, selected = _select_value_tier(client_values, ObjectTextState.CLIENT_FILL)
    if state is None:
        state, selected = _select_value_tier(cache_values, ObjectTextState.CACHE_FILL)
    if state is None:
        state = (
            ObjectTextState.AUTHOR_UNDEFINED
            if client_text_available
            else ObjectTextState.SOURCE_UNAVAILABLE
        )
        selected = (synthetic_text_evidence(identity),)
    placeholders = tuple(row for row in map_values if row.placeholder and row.raw_value)
    retained = unique_text_evidence((*selected, *placeholders))
    conflict_group = (
        _conflict_group(identity, selected)
        if state is ObjectTextState.SOURCE_CONFLICT
        else ""
    )
    return tuple(
        _ResolvedEvidence(
            row,
            state,
            "" if row.placeholder else conflict_group,
        )
        for row in retained
    )


def _select_map_tier(
    values: tuple[TextEvidence, ...],
) -> tuple[ObjectTextState | None, tuple[TextEvidence, ...]]:
    explicit_empty = tuple(row for row in values if row.raw_value == "")
    if explicit_empty:
        return ObjectTextState.MAP_EXPLICIT_EMPTY, explicit_empty
    return _select_value_tier(values, ObjectTextState.MAP_VALUE)


def _select_value_tier(
    values: tuple[TextEvidence, ...],
    success_state: ObjectTextState,
) -> tuple[ObjectTextState | None, tuple[TextEvidence, ...]]:
    usable = tuple(row for row in values if not row.placeholder)
    raw_values = {row.raw_value for row in usable}
    if len(raw_values) > 1:
        return ObjectTextState.SOURCE_CONFLICT, usable
    if usable:
        return success_state, usable
    return None, ()


def _to_record(
    item: GameObject,
    resolved: _ResolvedEvidence,
    ordinal: int,
) -> ObjectTextRecord:
    row = resolved.evidence
    return ObjectTextRecord(
        item.category,
        item.obj_id,
        item.base_id,
        item.name,
        item.is_custom,
        row.role,
        row.field_key,
        row.field_label,
        row.level,
        row.raw_value,
        readable_text(row.raw_value),
        row.source_kind,
        row.source_path,
        resolved.state,
        row.placeholder,
        resolved.conflict_group,
        ordinal,
    )


def _conflict_group(identity: TextIdentity, values: tuple[TextEvidence, ...]) -> str:
    payload = "\x1f".join((*map(str, identity), *(row.raw_value for row in values)))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _resolved_sort_key(
    value: tuple[GameObject, _ResolvedEvidence],
) -> tuple[str, str, str, int, str, str]:
    item, resolved = value
    row = resolved.evidence
    return (
        item.category.casefold(),
        item.obj_id,
        row.role.casefold(),
        -1 if row.level is None else row.level,
        row.source_path.casefold(),
        row.raw_value,
    )
