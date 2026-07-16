"""Resolve lossless map, client, and trusted-cache object text."""

from __future__ import annotations

from collections.abc import Iterable
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
)
from .object_text_models import ObjectTextIndex, ObjectTextRecord
from .object_text_roles import semantic_field_for_role
from .object_text_selection import SelectedTextEvidence, select_text_identity

if TYPE_CHECKING:
    from .client_object_data import ClientBaseObject
    from .map_data import GameObject


type _FieldIdentity = tuple[str, str, int | None]

_EXPECTED_FIELDS: Final = {
    "单位": (
        ("tip", "基础提示"),
        ("ubertip", "扩展提示"),
        ("revivetip", "复活提示"),
        ("awakentip", "唤醒提示"),
        ("editordescription", "编辑器描述"),
    ),
    "物品": (
        ("tip", "基础提示"),
        ("ubertip", "扩展提示"),
        ("editordescription", "编辑器描述"),
    ),
    "技能": (
        ("tip", "基础提示"),
        ("ubertip", "扩展提示"),
        ("researchtip", "学习提示"),
        ("researchubertip", "学习扩展提示"),
        ("untip", "关闭提示"),
        ("unubertip", "关闭扩展提示"),
    ),
    "科技": (("tip", "基础提示"), ("ubertip", "扩展提示")),
    "增益": (
        ("tip", "Buff提示"),
        ("ubertip", "Buff扩展提示"),
        ("editordescription", "编辑器描述"),
    ),
    "可破坏物": (("editordescription", "编辑器描述"),),
    "装饰物": (("editordescription", "编辑器描述"),),
}


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
    map_fields = _field_index(map_evidence)
    client_fields = _field_index(client_evidence)
    cache_fields = _cache_field_index(cache)
    resolved: list[tuple[GameObject, SelectedTextEvidence]] = []
    for item in object_rows:
        identities = _identities_for_object(
            item,
            map_fields,
            client_fields,
            cache_fields,
        )
        for semantic_field, role, level in identities:
            key = (item.category, item.obj_id, semantic_field, role, level)
            base_key = (item.category, item.base_id, semantic_field, role, level)
            evidence = select_text_identity(
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
    map_fields: dict[tuple[str, str], set[_FieldIdentity]],
    client_fields: dict[tuple[str, str], set[_FieldIdentity]],
    cache_fields: dict[tuple[str, str], set[_FieldIdentity]],
) -> tuple[_FieldIdentity, ...]:
    identities: set[_FieldIdentity] = {
        (semantic_field, role, None)
        for semantic_field, role in _EXPECTED_FIELDS.get(item.category, ())
    }
    identities.update(map_fields.get((item.category, item.obj_id), ()))
    identities.update(client_fields.get((item.category, item.base_id), ()))
    identities.update(cache_fields.get((item.category, item.base_id), ()))
    return tuple(
        sorted(
            identities,
            key=lambda value: (
                value[1].casefold(),
                value[0].casefold(),
                -1 if value[2] is None else value[2],
            ),
        )
    )


def _field_index(
    evidence: dict[TextIdentity, tuple[TextEvidence, ...]],
) -> dict[tuple[str, str], set[_FieldIdentity]]:
    indexed: dict[tuple[str, str], set[_FieldIdentity]] = {}
    for category, object_id, semantic_field, role, level in evidence:
        indexed.setdefault((category, object_id), set()).add(
            (semantic_field, role, level)
        )
    return indexed


def _cache_field_index(
    cache: DescriptionCache,
) -> dict[tuple[str, str], set[_FieldIdentity]]:
    indexed: dict[tuple[str, str], set[_FieldIdentity]] = {}
    for entry in cache.entries:
        indexed.setdefault((entry.category, entry.base_id), set()).add(
            (
                semantic_field_for_role(entry.role),
                entry.role,
                entry.level,
            )
        )
    return indexed


def _to_record(
    item: GameObject,
    resolved: SelectedTextEvidence,
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
        row.semantic_field,
        row.field_key,
        row.field_label,
        row.level,
        row.raw_value,
        readable_text(row.raw_value),
        row.source_kind,
        row.source_path,
        row.source_priority,
        resolved.state,
        row.placeholder,
        resolved.conflict_group,
        resolved.is_current,
        resolved.selection_reason,
        ordinal,
    )


def _resolved_sort_key(
    value: tuple[GameObject, SelectedTextEvidence],
) -> tuple[str, str, str, str, int, int, str, str]:
    item, resolved = value
    row = resolved.evidence
    return (
        item.category.casefold(),
        item.obj_id,
        row.role.casefold(),
        row.semantic_field.casefold(),
        -1 if row.level is None else row.level,
        -row.source_priority,
        row.source_path.casefold(),
        row.raw_value,
    )
