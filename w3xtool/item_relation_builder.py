"""Build and combine item acquisition and equipment-skill relations."""

from __future__ import annotations

from collections.abc import Iterable

from .doo import Unit
from .doo_drops import DropEntry
from .item_relation_endpoints import doo_evidence, relation_resolution, resolve_relation_object
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
from .item_relation_scripts import build_script_item_relations
from .map_data import MapData


def build_structural_item_relations(md: MapData) -> tuple[ItemRelation, ...]:
    """Return DOO, shop, placement, inventory, and equipment-skill evidence."""
    rows: list[ItemRelation] = []
    rows.extend(_unit_placement_relations(md))
    rows.extend(_doodad_drop_relations(md))
    rows.extend(object_field_relations(md))
    return tuple(rows)


def build_item_relation_index(md: MapData) -> ItemRelationIndex:
    """Build one immutable index from every supported static relation channel."""
    rows = list(build_structural_item_relations(md))
    rows.extend(build_recipe_item_relations(md))
    rows.extend(build_script_item_relations(md))
    return ItemRelationIndex.build(rows)


def _unit_placement_relations(md: MapData) -> Iterable[ItemRelation]:
    for unit in md.units:
        source, source_resolved = resolve_relation_object(md, unit.type_id, "单位")
        for group in unit.drop_sets:
            for entry in group.entries:
                yield _unit_drop_relation(md, unit, source, source_resolved, entry)
        resolved = md.obj_index.get(unit.type_id)
        if resolved is not None and resolved.category == "物品":
            item = RelationObject("物品", resolved.obj_id, resolved.name)
            yield _ground_placement_relation(md, unit, item)
            continue
        for slot, item_id in unit.items:
            item, item_resolved = resolve_relation_object(md, item_id, "物品")
            completeness, reason = relation_resolution(source_resolved, item_resolved)
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
                evidence=doo_evidence("war3mapUnits.doo", unit.source_offset, unit.serial),
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
        completeness=RelationCompleteness.COMPLETE,
        map_name=md.name,
    )


def _doodad_drop_relations(md: MapData) -> Iterable[ItemRelation]:
    for doodad in md.doodads:
        source, source_resolved = resolve_relation_object(md, doodad.type_id, "可破坏物")
        for group in doodad.drop_sets:
            for entry in group.entries:
                item, item_resolved = resolve_relation_object(md, entry.item_id, "物品")
                completeness, reason = relation_resolution(source_resolved, item_resolved)
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
                    evidence=doo_evidence("war3map.doo", entry.source_offset, doodad.serial),
                    confidence=RelationConfidence.CONFIRMED,
                    completeness=completeness,
                    unresolved_reason=reason,
                    map_name=md.name,
                )
