"""Structural item acquisition and equipment-skill relations."""

from w3xtool.doo import Doodad, Unit
from w3xtool.doo_drops import DropEntry, DropSet
from w3xtool.item_relation_builder import (
    build_item_relation_index,
    build_structural_item_relations,
)
from w3xtool.item_relation_models import ItemRelationKind, RelationCompleteness
from w3xtool.map_data import GameObject, MapData


def _object(
    category: str,
    object_id: str,
    name: str,
    *,
    fields: dict[str, str] | None = None,
) -> GameObject:
    values = fields or {}
    return GameObject(
        category=category,
        ext="w3t" if category == "物品" else "w3u",
        obj_id=object_id,
        base_id=object_id,
        name=name,
        is_custom=True,
        field_values=dict(values),
        field_sources={key: f"objects/{object_id}.txt" for key in values},
        field_labels={key: key for key in values},
    )


def _map_with_structural_sources() -> MapData:
    item = _object(
        "物品",
        "I001",
        "目标装备",
        fields={"abilList": "A001,A404", "cooldownID": "A002"},
    )
    objects = (
        item,
        _object("物品", "I002", "背包装备"),
        _object("物品", "I003", "地面装备"),
        _object("技能", "A001", "装备技能"),
        _object("技能", "A002", "冷却技能"),
        _object("单位", "n001", "掉落怪"),
        _object(
            "单位",
            "nshp",
            "装备商店",
            fields={"Sellitems": "I001,I002", "Makeitems": "I003"},
        ),
        _object("可破坏物", "D001", "宝箱"),
    )
    md = MapData(path="x.w3x", name="关系图")
    md.objects = {
        category: [item for item in objects if item.category == category]
        for category in {item.category for item in objects}
    }
    md.obj_index = {item.obj_id: item for item in objects}
    md.units = [
        Unit(
            "n001",
            0,
            0.0,
            0.0,
            0.0,
            0.0,
            player=3,
            serial=7,
            drop_sets=(DropSet(0, (DropEntry("I001", 35, 0, 0, 96),)),),
        ),
        Unit(
            "nshp",
            0,
            128.0,
            -64.0,
            0.0,
            0.0,
            player=11,
            items=[(2, "I002")],
            serial=41,
            source_offset=200,
        ),
        Unit(
            "nshp",
            0,
            256.0,
            -32.0,
            1.0,
            0.0,
            player=12,
            serial=42,
            source_offset=300,
        ),
        Unit("I003", 0, 512.0, 64.0, 2.0, 0.0, player=15, serial=43, source_offset=400),
    ]
    md.doodads = [
        Doodad(
            "D001",
            0,
            32.0,
            48.0,
            0.0,
            0.0,
            serial=8,
            drop_sets=(DropSet(1, (DropEntry("I002", 100, 1, 0, 144),)),),
            source_offset=120,
        ),
    ]
    return md


def test_structural_builder_emits_every_static_relation_kind() -> None:
    # Given: drops, shops, a ground item, inventory, and item skill fields.
    md = _map_with_structural_sources()

    # When: structural evidence is converted into relations.
    records = build_structural_item_relations(md)

    # Then: each source remains a distinct relation kind.
    assert {row.kind for row in records} >= {
        ItemRelationKind.UNIT_DROP,
        ItemRelationKind.DESTRUCTABLE_DROP,
        ItemRelationKind.SHOP_SELL,
        ItemRelationKind.SHOP_MAKE,
        ItemRelationKind.GROUND_PLACEMENT,
        ItemRelationKind.PREPLACED_INVENTORY,
        ItemRelationKind.ITEM_ABILITY,
        ItemRelationKind.COOLDOWN_ABILITY,
    }


def test_shop_relations_expand_to_every_preplaced_instance() -> None:
    # Given: one shop type is preplaced twice for different players.
    md = _map_with_structural_sources()

    # When: structural relations are built.
    records = build_structural_item_relations(md)

    # Then: its sold item has one evidence row per concrete instance.
    rows = [
        row
        for row in records
        if row.kind is ItemRelationKind.SHOP_SELL and row.item.object_id == "I001"
    ]
    assert {(row.instance_serial, row.player, row.x, row.y) for row in rows} == {
        (41, 11, 128.0, -64.0),
        (42, 12, 256.0, -32.0),
    }


def test_drops_keep_group_entry_probability_and_binary_offset() -> None:
    # Given: a unit and destructable with nested binary drop evidence.
    md = _map_with_structural_sources()

    # When: relations are built.
    records = build_structural_item_relations(md)

    # Then: the original nested identity and source offset survive unchanged.
    unit = next(row for row in records if row.kind is ItemRelationKind.UNIT_DROP)
    destructable = next(
        row for row in records if row.kind is ItemRelationKind.DESTRUCTABLE_DROP
    )
    assert (unit.group_index, unit.entry_index, unit.chance, unit.evidence.offset) == (
        0,
        0,
        35,
        96,
    )
    assert (
        destructable.group_index,
        destructable.entry_index,
        destructable.chance,
        destructable.evidence.offset,
    ) == (1, 0, 100, 144)


def test_item_skill_relations_keep_unknown_skill_as_unresolved_evidence() -> None:
    # Given: one item field references two known skills and one unknown skill.
    md = _map_with_structural_sources()

    # When: relations are built.
    records = build_structural_item_relations(md)

    # Then: known roles are queryable and the unknown code is not discarded.
    skill_rows = [
        row
        for row in records
        if row.kind in {ItemRelationKind.ITEM_ABILITY, ItemRelationKind.COOLDOWN_ABILITY}
    ]
    assert {row.skill.object_id for row in skill_rows if row.skill is not None} == {
        "A001",
        "A002",
        "A404",
    }
    unresolved = next(
        row for row in skill_rows if row.skill is not None and row.skill.object_id == "A404"
    )
    assert unresolved.skill is not None
    assert unresolved.skill.name == "未解析"
    assert unresolved.completeness is RelationCompleteness.UNRESOLVED
    assert unresolved.unresolved_reason


def test_item_skill_relation_does_not_misclassify_equipment_as_a_source() -> None:
    # Given: one item provides indexed ability and shared-cooldown relations.
    md = _map_with_structural_sources()

    # When: object fields are converted into the unified relation index.
    skill_rows = tuple(
        row
        for row in build_structural_item_relations(md)
        if row.kind
        in {ItemRelationKind.ITEM_ABILITY, ItemRelationKind.COOLDOWN_ABILITY}
    )

    # Then: the item remains the equipment endpoint, not an acquisition source.
    assert skill_rows
    assert all(row.source is None for row in skill_rows)


def test_shop_without_placement_remains_as_partial_type_level_evidence() -> None:
    # Given: a defined shop has no preplaced instance.
    shop = _object("单位", "nshp", "动态商店", fields={"Sellitems": "I001"})
    item = _object("物品", "I001", "目标装备")
    md = MapData(path="x.w3x", name="动态商店图", objects={"单位": [shop], "物品": [item]})
    md.obj_index = {shop.obj_id: shop, item.obj_id: item}

    # When: structural relations are built.
    (row,) = build_structural_item_relations(md)

    # Then: the proven sale survives while its missing position is explicit.
    assert row.kind is ItemRelationKind.SHOP_SELL
    assert row.instance_serial is None
    assert row.completeness is RelationCompleteness.PARTIAL
    assert "未预放置" in row.unresolved_reason


def test_combined_index_counts_recipe_materials_and_preserves_source_evidence() -> None:
    # Given: a source-aware recipe with a duplicate material.
    objects = (
        _object("物品", "I001", "材料甲"),
        _object("物品", "I002", "材料乙"),
        _object("物品", "I999", "成品"),
    )
    script = "\n".join((
        "function Forge takes nothing returns nothing",
        "call RemoveItem(GetItemOfTypeFromUnitBJ(u, 'I001'))",
        "call RemoveItem(GetItemOfTypeFromUnitBJ(u, 'I001'))",
        "call RemoveItem(GetItemOfTypeFromUnitBJ(u, 'I002'))",
        "call UnitAddItemById(u, 'I999')",
        "endfunction",
    ))
    md = MapData(path="x.w3x", name="配方图", scripts={"war3map.j": script})
    md.objects = {"物品": list(objects)}
    md.obj_index = {item.obj_id: item for item in objects}

    # When: every relation channel is combined into one immutable index.
    index = build_item_relation_index(md)

    # Then: the recipe retains counted ingredients and source/function/line evidence.
    recipe = next(row for row in index.records if row.kind is ItemRelationKind.RECIPE)
    assert [(entry.item.object_id, entry.count) for entry in recipe.ingredients] == [
        ("I001", 2),
        ("I002", 1),
    ]
    assert (
        recipe.evidence.source,
        recipe.evidence.function,
        recipe.evidence.line,
    ) == ("war3map.j", "Forge", 5)
