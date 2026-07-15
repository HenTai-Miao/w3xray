"""Build shop and equipment-skill relations from object fields."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import assert_never

from .doo import Unit
from .item_relation_endpoints import (
    object_field_evidence,
    placement_resolution,
    resolve_relation_object,
)
from .item_relation_field_variants import (
    relation_field_variants,
    relation_objects,
    split_relation_codes,
)
from .item_relation_models import (
    ItemRelation,
    ItemRelationKind,
    RelationCompleteness,
    RelationConfidence,
    RelationObject,
)
from .map_data import GameObject, GameObjectFieldEvidence, MapData


def object_field_relations(md: MapData) -> Iterable[ItemRelation]:
    """Yield shop inventory and equipment-skill object-field evidence."""
    units_by_type: dict[str, list[Unit]] = {}
    for unit in md.units:
        units_by_type.setdefault(unit.type_id, []).append(unit)
    for obj in relation_objects(md):
        for variant in relation_field_variants(obj):
            kind = variant.kind
            field = variant.field
            codes = split_relation_codes(field.source_value)
            match kind:
                case ItemRelationKind.SHOP_SELL | ItemRelationKind.SHOP_MAKE:
                    for code in codes:
                        yield from _shop_relations(
                            md,
                            obj,
                            field,
                            code,
                            kind,
                            units_by_type,
                            variant.conflict,
                        )
                case ItemRelationKind.ITEM_ABILITY | ItemRelationKind.COOLDOWN_ABILITY:
                    if obj.category == "物品":
                        for code in codes:
                            yield _skill_relation(
                                md,
                                obj,
                                field,
                                code,
                                kind,
                                variant.conflict,
                            )
                case (
                    ItemRelationKind.UNIT_DROP
                    | ItemRelationKind.DESTRUCTABLE_DROP
                    | ItemRelationKind.RECIPE
                    | ItemRelationKind.GROUND_PLACEMENT
                    | ItemRelationKind.PREPLACED_INVENTORY
                    | ItemRelationKind.SCRIPT_REWARD
                ):
                    raise AssertionError("对象字段角色表包含不支持的关系类型")
                case unreachable:
                    assert_never(unreachable)


def _shop_relations(
    md: MapData,
    shop: GameObject,
    field: GameObjectFieldEvidence,
    item_id: str,
    kind: ItemRelationKind,
    units_by_type: Mapping[str, list[Unit]],
    conflict: bool,
) -> Iterable[ItemRelation]:
    item, item_resolved = resolve_relation_object(md, item_id, "物品")
    source = RelationObject(shop.category, shop.obj_id, shop.name)
    instances = units_by_type.get(shop.obj_id, [])
    evidence = object_field_evidence(
        shop,
        field.key,
        field.source_value,
        source=field.source,
    )
    if not instances:
        reason = "未预放置；商店可能由脚本创建"
        if not item_resolved:
            reason = f"物品 {item_id} 未解析；{reason}"
        completeness = (
            RelationCompleteness.PARTIAL
            if item_resolved
            else RelationCompleteness.UNRESOLVED
        )
        completeness, reason = placement_resolution(
            md,
            "war3mapUnits.doo",
            completeness,
            reason,
        )
        completeness, reason = _conflict_resolution(completeness, reason, conflict)
        yield ItemRelation(
            kind=kind,
            item=item,
            source=source,
            evidence=evidence,
            confidence=RelationConfidence.CONFIRMED,
            completeness=completeness,
            unresolved_reason=reason,
            map_name=md.name,
        )
        return
    for unit in instances:
        completeness = (
            RelationCompleteness.COMPLETE
            if item_resolved
            else RelationCompleteness.UNRESOLVED
        )
        reason = "" if item_resolved else f"物品 {item_id} 未解析"
        completeness, reason = placement_resolution(
            md,
            "war3mapUnits.doo",
            completeness,
            reason,
        )
        completeness, reason = _conflict_resolution(completeness, reason, conflict)
        yield ItemRelation(
            kind=kind,
            item=item,
            source=source,
            instance_serial=unit.serial,
            player=unit.player,
            x=unit.x,
            y=unit.y,
            z=unit.z,
            evidence=evidence,
            confidence=RelationConfidence.CONFIRMED,
            completeness=completeness,
            unresolved_reason=reason,
            map_name=md.name,
        )


def _skill_relation(
    md: MapData,
    item_obj: GameObject,
    field: GameObjectFieldEvidence,
    skill_id: str,
    kind: ItemRelationKind,
    conflict: bool,
) -> ItemRelation:
    item = RelationObject("物品", item_obj.obj_id, item_obj.name)
    skill, resolved = resolve_relation_object(md, skill_id, "技能")
    completeness = (
        RelationCompleteness.COMPLETE if resolved else RelationCompleteness.UNRESOLVED
    )
    reason = "" if resolved else f"技能 {skill_id} 未解析"
    completeness, reason = _conflict_resolution(completeness, reason, conflict)
    return ItemRelation(
        kind=kind,
        item=item,
        skill=skill,
        evidence=object_field_evidence(
            item_obj,
            field.key,
            field.source_value,
            source=field.source,
        ),
        confidence=RelationConfidence.CONFIRMED,
        completeness=completeness,
        unresolved_reason=reason,
        map_name=md.name,
    )


def _conflict_resolution(
    completeness: RelationCompleteness,
    reason: str,
    conflict: bool,
) -> tuple[RelationCompleteness, str]:
    if not conflict:
        return completeness, reason
    detail = "同优先级对象字段值冲突"
    return RelationCompleteness.CONFLICT, "；".join(
        value for value in (reason, detail) if value
    )
