"""Resolve relation endpoints and common placement evidence."""

from __future__ import annotations

from .base_names import BASE_NAMES
from .item_relation_models import (
    RelationCompleteness,
    RelationEvidence,
    RelationObject,
)
from .map_data import GameObject, MapData


def resolve_relation_object(
    md: MapData,
    object_id: str,
    category: str,
) -> tuple[RelationObject, bool]:
    """Resolve an endpoint while retaining unknown literal IDs."""
    resolved = md.obj_index.get(object_id)
    if resolved is not None:
        return RelationObject(resolved.category, resolved.obj_id, resolved.name), True
    name = BASE_NAMES.get(object_id)
    return RelationObject(category, object_id, name or "未解析"), name is not None


def relation_resolution(
    source_resolved: bool,
    item_resolved: bool,
) -> tuple[RelationCompleteness, str]:
    """Describe unresolved structural endpoints without discarding evidence."""
    missing: list[str] = []
    if not source_resolved:
        missing.append("来源对象未解析")
    if not item_resolved:
        missing.append("物品未解析")
    if missing:
        return RelationCompleteness.UNRESOLVED, "；".join(missing)
    return RelationCompleteness.COMPLETE, ""


def object_field_evidence(obj: GameObject, key: str, raw: str) -> RelationEvidence:
    """Retain the exact object-field source, key, and raw value."""
    source = obj.field_sources.get(key, "对象字段")
    return RelationEvidence(source=source, field_key=key, location=key, raw=raw)


def doo_evidence(source: str, offset: int, serial: int) -> RelationEvidence:
    """Build a stable placement file and binary-offset evidence record."""
    location = f"实例 {serial} @ 0x{offset:X}" if offset else f"实例 {serial}"
    return RelationEvidence(source=source, offset=offset, location=location)
