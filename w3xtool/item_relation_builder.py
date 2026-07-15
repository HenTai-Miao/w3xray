"""Build and combine item acquisition and equipment-skill relations."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from .doo import Unit
from .doo_drops import DropEntry
from .extraction_diagnostics import record_component_failure
from .item_relation_endpoints import (
    doo_evidence,
    find_relation_game_object,
    placement_resolution,
    relation_resolution,
    resolve_relation_object,
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
    for unit in md.units:
        source, source_resolved = resolve_relation_object(md, unit.type_id, "单位")
        for group in unit.drop_sets:
            for entry in group.entries:
                yield _unit_drop_relation(md, unit, source, source_resolved, entry)
        resolved = find_relation_game_object(md, unit.type_id, "物品")
        if resolved is not None:
            item = RelationObject("物品", resolved.obj_id, resolved.name)
            yield _ground_placement_relation(md, unit, item)
            continue
        for slot, item_id in unit.items:
            item, item_resolved = resolve_relation_object(md, item_id, "物品")
            completeness, reason = relation_resolution(source_resolved, item_resolved)
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
                confidence=RelationConfidence.CONFIRMED,
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
) -> ItemRelation:
    item, item_resolved = resolve_relation_object(md, entry.item_id, "物品")
    completeness, reason = relation_resolution(source_resolved, item_resolved)
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
        confidence=RelationConfidence.CONFIRMED,
        completeness=completeness,
        unresolved_reason=reason,
        map_name=md.name,
    )


def _ground_placement_relation(
    md: MapData,
    unit: Unit,
    item: RelationObject,
) -> ItemRelation:
    completeness, reason = placement_resolution(
        md,
        "war3mapUnits.doo",
        RelationCompleteness.COMPLETE,
        "",
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
        confidence=RelationConfidence.CONFIRMED,
        completeness=completeness,
        unresolved_reason=reason,
        map_name=md.name,
    )


def _doodad_drop_relations(md: MapData) -> Iterable[ItemRelation]:
    for doodad in md.doodads:
        source, source_resolved = resolve_relation_object(
            md, doodad.type_id, "可破坏物"
        )
        for group in doodad.drop_sets:
            for entry in group.entries:
                item, item_resolved = resolve_relation_object(md, entry.item_id, "物品")
                completeness, reason = relation_resolution(
                    source_resolved, item_resolved
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
                    confidence=RelationConfidence.CONFIRMED,
                    completeness=completeness,
                    unresolved_reason=reason,
                    map_name=md.name,
                )


def _extend_relation_channel(
    rows: list[ItemRelation],
    md: MapData,
    source: str,
    builder: Callable[[MapData], Iterable[ItemRelation]],
) -> None:
    try:
        rows.extend(builder(md))
    except Exception as exc:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK - independent analysis boundary.
        record_component_failure(
            md,
            "item-relations",
            source,
            exc,
            stage="analyze",
        )
