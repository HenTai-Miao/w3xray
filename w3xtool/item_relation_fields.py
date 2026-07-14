"""Build shop and equipment-skill relations from object fields."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import Final, assert_never

from .doo import Unit
from .item_relation_endpoints import object_field_evidence, resolve_relation_object
from .item_relation_models import (
    ItemRelation,
    ItemRelationKind,
    RelationCompleteness,
    RelationConfidence,
    RelationObject,
)
from .map_data import GameObject, MapData

_FIELD_ROLES: Final[Mapping[str, ItemRelationKind]] = MappingProxyType({
    "sellitems": ItemRelationKind.SHOP_SELL,
    "usei": ItemRelationKind.SHOP_SELL,
    "makeitems": ItemRelationKind.SHOP_MAKE,
    "umki": ItemRelationKind.SHOP_MAKE,
    "abillist": ItemRelationKind.ITEM_ABILITY,
    "iabi": ItemRelationKind.ITEM_ABILITY,
    "cooldownid": ItemRelationKind.COOLDOWN_ABILITY,
    "icid": ItemRelationKind.COOLDOWN_ABILITY,
})
_PLACEHOLDER_CODES: Final = frozenset(("____", "----", "0000"))


def object_field_relations(md: MapData) -> Iterable[ItemRelation]:
    """Yield shop inventory and equipment-skill object-field evidence."""
    units_by_type: dict[str, list[Unit]] = {}
    for unit in md.units:
        units_by_type.setdefault(unit.type_id, []).append(unit)
    for obj in md.obj_index.values():
        for key, raw in obj.field_values.items():
            kind = _FIELD_ROLES.get(key.casefold())
            if kind is None:
                continue
            codes = _split_codes(raw)
            match kind:
                case ItemRelationKind.SHOP_SELL | ItemRelationKind.SHOP_MAKE:
                    for code in codes:
                        yield from _shop_relations(
                            md,
                            obj,
                            key,
                            raw,
                            code,
                            kind,
                            units_by_type,
                        )
                case ItemRelationKind.ITEM_ABILITY | ItemRelationKind.COOLDOWN_ABILITY:
                    if obj.category == "物品":
                        for code in codes:
                            yield _skill_relation(md, obj, key, raw, code, kind)
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
    key: str,
    raw: str,
    item_id: str,
    kind: ItemRelationKind,
    units_by_type: Mapping[str, list[Unit]],
) -> Iterable[ItemRelation]:
    item, item_resolved = resolve_relation_object(md, item_id, "物品")
    source = RelationObject(shop.category, shop.obj_id, shop.name)
    instances = units_by_type.get(shop.obj_id, [])
    evidence = object_field_evidence(shop, key, raw)
    if not instances:
        reason = "未预放置；商店可能由脚本创建"
        if not item_resolved:
            reason = f"物品 {item_id} 未解析；{reason}"
        yield ItemRelation(
            kind=kind,
            item=item,
            source=source,
            evidence=evidence,
            confidence=RelationConfidence.CONFIRMED,
            completeness=(
                RelationCompleteness.PARTIAL
                if item_resolved
                else RelationCompleteness.UNRESOLVED
            ),
            unresolved_reason=reason,
            map_name=md.name,
        )
        return
    for unit in instances:
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
            completeness=(
                RelationCompleteness.COMPLETE
                if item_resolved
                else RelationCompleteness.UNRESOLVED
            ),
            unresolved_reason="" if item_resolved else f"物品 {item_id} 未解析",
            map_name=md.name,
        )


def _skill_relation(
    md: MapData,
    item_obj: GameObject,
    key: str,
    raw: str,
    skill_id: str,
    kind: ItemRelationKind,
) -> ItemRelation:
    item = RelationObject("物品", item_obj.obj_id, item_obj.name)
    skill, resolved = resolve_relation_object(md, skill_id, "技能")
    return ItemRelation(
        kind=kind,
        item=item,
        source=item,
        skill=skill,
        evidence=object_field_evidence(item_obj, key, raw),
        confidence=RelationConfidence.CONFIRMED,
        completeness=(
            RelationCompleteness.COMPLETE if resolved else RelationCompleteness.UNRESOLVED
        ),
        unresolved_reason="" if resolved else f"技能 {skill_id} 未解析",
        map_name=md.name,
    )


def _split_codes(raw: str) -> tuple[str, ...]:
    codes: list[str] = []
    for token in raw.replace("|", ",").split(","):
        code = token.strip().strip("\x00")
        if len(code) != 4 or code in _PLACEHOLDER_CODES or code.isdigit():
            continue
        if code not in codes:
            codes.append(code)
    return tuple(codes)
