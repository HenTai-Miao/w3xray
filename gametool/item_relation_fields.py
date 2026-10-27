"""Build shop and equipment-skill relations from object fields."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import replace
from typing import assert_never

from .doo import Unit
from .item_relation_endpoints import (
    object_field_evidence,
    placement_resolution,
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
from .placement_identity import PlacementObjectIndex


def object_field_relations(md: MapData) -> Iterable[ItemRelation]:
    """Yield shop inventory and equipment-skill object-field evidence."""
    objects = PlacementObjectIndex(md)
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
                    if obj.category not in ("单位", "英雄"):
                        continue
                    for code in codes:
                        yield from _shop_relations(
                            md,
                            obj,
                            field,
                            code,
                            kind,
                            units_by_type,
                            variant.conflict,
                            objects,
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
                                objects,
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
    objects: PlacementObjectIndex,
) -> Iterable[ItemRelation]:
    item, item_resolved = _field_object(objects, item_id, "物品")
    source = RelationObject(
        "单位" if shop.category == "英雄" else shop.category, shop.obj_id, shop.name
    )
    instances = units_by_type.get(shop.obj_id, [])
    identity = objects.placement(shop.obj_id, ("单位", "物品"))
    position_confirmed = identity.category == "单位"
    evidence = object_field_evidence(
        shop,
        field.key,
        field.source_value,
        source=field.source,
    )
    if not instances or not position_confirmed:
        reason = (
            "未预放置；商店可能由脚本创建"
            if not instances
            else "货架字段已确认，尚无已确认预放置位置；" + identity.diagnostic
        )
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
        if not instances:
            return
    for unit in instances:
        completeness = (
            RelationCompleteness.COMPLETE
            if item_resolved
            else RelationCompleteness.UNRESOLVED
        )
        reason = "" if item_resolved else f"物品 {item_id} 未解析"
        confidence = RelationConfidence.CONFIRMED
        if not position_confirmed:
            confidence = RelationConfidence.CLUE
            completeness = (
                RelationCompleteness.CONFLICT
                if identity.category or len(identity.candidates) > 1
                else RelationCompleteness.UNRESOLVED
            )
            reason = "；".join(
                value
                for value in (
                    identity.diagnostic or "商店预放置分类未确认",
                    "位置仅为候选",
                    reason,
                )
                if value
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
            instance_serial=unit.serial,
            player=unit.player,
            x=unit.x,
            y=unit.y,
            z=unit.z,
            evidence=replace(
                evidence,
                location="；".join(
                    value
                    for value in (
                        evidence.location,
                        f"war3mapUnits.doo 实例{unit.serial} @0x{unit.source_offset:X}",
                    )
                    if value
                ),
            ),
            confidence=confidence,
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
    objects: PlacementObjectIndex,
) -> ItemRelation:
    item = RelationObject("物品", item_obj.obj_id, item_obj.name)
    skill, resolved = _field_object(objects, skill_id, "技能")
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


def _field_object(
    objects: PlacementObjectIndex, code: str, category: str
) -> tuple[RelationObject, bool]:
    label = objects.placement(code, (category,))
    return RelationObject(
        category, code, label.name if label.category else "未解析", label.fine
    ), bool(label.category)


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
