"""Resolve relation endpoints and common placement evidence."""

from __future__ import annotations

from .base_names import BASE_NAMES
from .base_objects import BASE_OBJECTS
from .item_relation_models import (
    RelationCompleteness,
    RelationEvidence,
    RelationObject,
)
from .map_data import GameObject, MapData


def find_relation_game_object(
    md: MapData,
    object_id: str,
    category: str,
) -> GameObject | None:
    """Find an explicit object without crossing a category boundary."""
    exact = md.obj_identity_index.get((category, object_id))
    if exact is not None:
        return exact
    legacy = md.obj_index.get(object_id)
    return legacy if legacy is not None and legacy.category == category else None


def resolve_relation_object(
    md: MapData,
    object_id: str,
    category: str,
) -> tuple[RelationObject, bool]:
    """Resolve an endpoint while retaining unknown literal IDs."""
    resolved = find_relation_game_object(md, object_id, category)
    if resolved is not None:
        has_object_data = resolved.ext != "script"
        name = resolved.name if has_object_data else "未解析"
        endpoint = RelationObject(resolved.category, resolved.obj_id, name)
        return endpoint, has_object_data
    base = BASE_OBJECTS.get(object_id)
    name = (
        BASE_NAMES.get(object_id) if base is not None and base[0] == category else None
    )
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


def object_field_evidence(
    obj: GameObject,
    key: str,
    raw: str,
    *,
    source: str = "",
) -> RelationEvidence:
    """Retain the exact object-field source, key, and raw value."""
    resolved_source = source or obj.field_sources.get(key, "对象字段")
    return RelationEvidence(
        source=resolved_source,
        field_key=key,
        location=key,
        raw=raw,
    )


def placement_incomplete_reason(md: MapData, source: str) -> str:
    """Return every retained partial-placement diagnostic for one DOO source."""
    normalized = source.replace("/", "\\").casefold()
    messages = tuple(
        row.message
        for row in md.diagnostics
        if row.component == "preplaced"
        and row.source.replace("/", "\\").casefold() == normalized
    )
    return "；".join(dict.fromkeys(messages))


def placement_resolution(
    md: MapData,
    source: str,
    completeness: RelationCompleteness,
    reason: str,
) -> tuple[RelationCompleteness, str]:
    """Propagate a partial placement table without hiding endpoint failures."""
    placement_reason = placement_incomplete_reason(md, source)
    if not placement_reason:
        return completeness, reason
    combined = "；".join(value for value in (reason, placement_reason) if value)
    if completeness is RelationCompleteness.COMPLETE:
        return RelationCompleteness.PARTIAL, combined
    return completeness, combined


def doo_evidence(source: str, offset: int, serial: int) -> RelationEvidence:
    """Build a stable placement file and binary-offset evidence record."""
    location = f"实例 {serial} @ 0x{offset:X}" if offset else f"实例 {serial}"
    return RelationEvidence(source=source, offset=offset, location=location)
