"""Build and combine item acquisition and equipment-skill relations."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from .doo import Unit
from .doo_drops import DropEntry
from .extraction_diagnostics import record_component_failure
from .item_relation_endpoints import (
    doo_evidence,
    placement_resolution,
    relation_resolution,
)
from .item_relation_fields import object_field_relations
from .item_relation_models import (
    ItemRelation,
    ItemRelationIndex,
    ItemRelationKind,
    RelationCompleteness,
    RelationConfidence,
    RelationObject,
)
from .item_relation_recipes import build_recipe_item_relations
from .item_relation_scripts import build_script_call_item_relations
from .item_relation_wtg import build_wtg_item_relations
from .map_data import MapData
from .placement_identity import PlacementIdentity, PlacementObjectIndex


def build_structural_item_relations(md: MapData) -> tuple[ItemRelation, ...]:
    """Return DOO, shop, placement, inventory, and equipment-skill evidence."""
    rows: list[ItemRelation] = []
    _extend_relation_channel(rows, md, "unit-placements", _unit_placement_relations)
    _extend_relation_channel(rows, md, "destructable-drops", _doodad_drop_relations)
    _extend_relation_channel(rows, md, "object-fields", object_field_relations)
    return tuple(rows)


def build_item_relation_index(md: MapData) -> ItemRelationIndex:
    """Build one immutable index from every supported static relation channel."""
    rows = list(build_structural_item_relations(md))
    _extend_relation_channel(rows, md, "recipes", build_recipe_item_relations)
    _extend_relation_channel(rows, md, "scripts", build_script_call_item_relations)
    _extend_relation_channel(rows, md, "wtg", build_wtg_item_relations)
    return ItemRelationIndex.build(rows)


def _unit_placement_relations(md: MapData) -> Iterable[ItemRelation]:
    objects = PlacementObjectIndex(md)
    for unit in md.units:
        identity = objects.placement(unit.type_id, ("单位", "物品"))
        source, source_resolved = _placed_object(objects, unit.type_id, "单位")
        for group in unit.drop_sets:
            for entry in group.entries:
                yield _unit_drop_relation(
                    md, unit, source, source_resolved, entry, objects, identity
                )
        if "物品" in identity.candidates:
            item, _resolved = _placed_object(objects, unit.type_id, "物品")
            yield _ground_placement_relation(md, unit, item, identity)
        for slot, item_id in unit.items:
            item, item_resolved = _placed_object(objects, item_id, "物品")
            completeness, reason, confidence = _placed_state(
                identity, "单位", source_resolved, item_resolved
            )
            completeness, reason = placement_resolution(
                md,
                "war3mapUnits.doo",
                completeness,
                reason,
            )
            yield ItemRelation(
                kind=ItemRelationKind.PREPLACED_INVENTORY,
                item=item,
                source=source,
                instance_serial=unit.serial,
                player=unit.player,
                x=unit.x,
                y=unit.y,
                z=unit.z,
                slot=slot,
                evidence=doo_evidence(
                    "war3mapUnits.doo", unit.source_offset, unit.serial
                ),
                confidence=confidence,
                completeness=completeness,
                unresolved_reason=reason,
                map_name=md.name,
            )


def _unit_drop_relation(
    md: MapData,
    unit: Unit,
    source: RelationObject,
    source_resolved: bool,
    entry: DropEntry,
    objects: PlacementObjectIndex,
    identity: PlacementIdentity,
) -> ItemRelation:
    item, item_resolved = _placed_object(objects, entry.item_id, "物品")
    completeness, reason, confidence = _placed_state(
        identity, "单位", source_resolved, item_resolved
    )
    completeness, reason = placement_resolution(
        md,
        "war3mapUnits.doo",
        completeness,
        reason,
    )
    return ItemRelation(
        kind=ItemRelationKind.UNIT_DROP,
        item=item,
        source=source,
        instance_serial=unit.serial,
        player=unit.player,
        x=unit.x,
        y=unit.y,
        z=unit.z,
        group_index=entry.group_index,
        entry_index=entry.entry_index,
        chance=entry.chance,
        evidence=doo_evidence("war3mapUnits.doo", entry.source_offset, unit.serial),
        confidence=confidence,
        completeness=completeness,
        unresolved_reason=reason,
        map_name=md.name,
    )


def _ground_placement_relation(
    md: MapData,
    unit: Unit,
    item: RelationObject,
    identity: PlacementIdentity,
) -> ItemRelation:
    state, reason, confidence = _placed_state(identity, "物品", True, True)
    completeness, reason = placement_resolution(
        md,
        "war3mapUnits.doo",
        state,
        reason,
    )
    return ItemRelation(
        kind=ItemRelationKind.GROUND_PLACEMENT,
        item=item,
        instance_serial=unit.serial,
        player=unit.player,
        x=unit.x,
        y=unit.y,
        z=unit.z,
        evidence=doo_evidence("war3mapUnits.doo", unit.source_offset, unit.serial),
        confidence=confidence,
        completeness=completeness,
        unresolved_reason=reason,
        map_name=md.name,
    )


def _doodad_drop_relations(md: MapData) -> Iterable[ItemRelation]:
    objects = PlacementObjectIndex(md)
    for doodad in md.doodads:
        identity = objects.placement(doodad.type_id, ("装饰物", "可破坏物"))
        source, source_resolved = _placed_object(objects, doodad.type_id, "可破坏物")
        for group in doodad.drop_sets:
            for entry in group.entries:
                item, item_resolved = _placed_object(objects, entry.item_id, "物品")
                completeness, reason, confidence = _placed_state(
                    identity, "可破坏物", source_resolved, item_resolved
                )
                completeness, reason = placement_resolution(
                    md,
                    "war3map.doo",
                    completeness,
                    reason,
                )
                yield ItemRelation(
                    kind=ItemRelationKind.DESTRUCTABLE_DROP,
                    item=item,
                    source=source,
                    instance_serial=doodad.serial,
                    x=doodad.x,
                    y=doodad.y,
                    z=doodad.z,
                    group_index=entry.group_index,
                    entry_index=entry.entry_index,
                    chance=entry.chance,
                    evidence=doo_evidence(
                        "war3map.doo", entry.source_offset, doodad.serial
                    ),
                    confidence=confidence,
                    completeness=completeness,
                    unresolved_reason=reason,
                    map_name=md.name,
                )


def _placed_object(
    objects: PlacementObjectIndex, code: str, category: str
) -> tuple[RelationObject, bool]:
    label = objects.placement(code, (category,))
    return RelationObject(
        category, code, label.name if label.category else "未解析", label.fine
    ), bool(label.category)


def _placed_state(
    identity: PlacementIdentity,
    expected: str,
    source_resolved: bool,
    item_resolved: bool,
) -> tuple[RelationCompleteness, str, RelationConfidence]:
    state, reason = relation_resolution(source_resolved, item_resolved)
    if identity.category == expected:
        return state, reason, RelationConfidence.CONFIRMED
    state = (
        RelationCompleteness.CONFLICT
        if identity.category or len(identity.candidates) > 1
        else RelationCompleteness.UNRESOLVED
    )
    classification = (
        identity.diagnostic
        or f"放置分类为{identity.category}，{expected}字段关系仅为未确认线索"
    )
    return (
        state,
        "；".join(part for part in (classification, reason) if part),
        RelationConfidence.CLUE,
    )


def _extend_relation_channel(
    rows: list[ItemRelation],
    md: MapData,
    source: str,
    builder: Callable[[MapData], Iterable[ItemRelation]],
) -> None:
    try:
        rows.extend(builder(md))
    except Exception as exc:  # BROAD_EXCEPT_OK - independent analysis boundary.
        record_component_failure(
            md,
            "item-relations",
            source,
            exc,
            stage="analyze",
        )
