"""Category safety, conflict retention, and relation-channel resilience."""

from __future__ import annotations

import pytest

import w3xtool.item_relation_builder as relation_builder
from w3xtool.doo import Unit
from w3xtool.doo_drops import DropEntry, DropSet
from w3xtool.extraction_diagnostics import record_component_parse_issue
from w3xtool.item_relation_builder import (
    build_item_relation_index,
    build_structural_item_relations,
)
from w3xtool.item_relation_endpoints import resolve_relation_object
from w3xtool.item_relation_fields import object_field_relations
from w3xtool.item_relation_models import ItemRelationKind, RelationCompleteness
from w3xtool.item_relation_scripts import build_script_item_relations
from w3xtool.map_data import GameObject, GameObjectFieldEvidence, MapData


class _RelationChannelFailure(RuntimeError):
    """Synthetic top-level analysis failure."""


def test_relation_endpoint_resolves_requested_category_when_rawcodes_collide() -> None:
    # Given: legacy lookup points at a unit while the exact index also has an item.
    unit = _object("单位", "X001", "同码单位")
    item = _object("物品", "X001", "同码装备")
    md = _map(unit, item)
    md.obj_index = {"X001": unit}

    # When: a relation explicitly requests the item category.
    endpoint, resolved = resolve_relation_object(md, "X001", "物品")

    # Then: the category-safe endpoint wins over the compatibility index.
    assert resolved is True
    assert endpoint == relation_builder.RelationObject("物品", "X001", "同码装备")


def test_base_name_fallback_never_crosses_an_object_category() -> None:
    # Given: hfoo is a named base unit, but no item with that rawcode exists.
    md = _map()

    # When: an item relation references that unit rawcode.
    endpoint, resolved = resolve_relation_object(md, "hfoo", "物品")

    # Then: the unit name is not promoted into a resolved item endpoint.
    assert resolved is False
    assert endpoint == relation_builder.RelationObject("物品", "hfoo", "未解析")


def test_script_reference_placeholder_remains_an_unresolved_reward_endpoint() -> None:
    # Given: script scanning created a reference-only object with no object data.
    placeholder = GameObject("物品", "script", "I404", "I404", "I404", True)
    md = _map(placeholder)
    md.scripts = {"war3map.j": "call CreateItem('I404', 0.0, 0.0)"}

    # When: the fixed-code reward is converted into a relation.
    (row,) = build_script_item_relations(md)

    # Then: the reference is retained, but never promoted to resolved object data.
    assert row.item.object_id == "I404"
    assert row.item.name == "未解析"
    assert row.completeness is RelationCompleteness.UNRESOLVED
    assert row.unresolved_reason == "物品 I404 未解析"


@pytest.mark.parametrize(
    ("field_key", "kind", "owner_category", "target_category", "first", "second"),
    (
        ("Sellitems", ItemRelationKind.SHOP_SELL, "单位", "物品", "I001", "I002"),
        ("Makeitems", ItemRelationKind.SHOP_MAKE, "单位", "物品", "I001", "I002"),
        ("abilList", ItemRelationKind.ITEM_ABILITY, "物品", "技能", "A001", "A002"),
        (
            "cooldownID",
            ItemRelationKind.COOLDOWN_ABILITY,
            "物品",
            "技能",
            "A001",
            "A002",
        ),
    ),
)
def test_equal_priority_relation_field_conflicts_keep_every_variant(
    field_key: str,
    kind: ItemRelationKind,
    owner_category: str,
    target_category: str,
    first: str,
    second: str,
) -> None:
    # Given: two top-priority sources disagree on one relation-bearing field.
    owner = _object(owner_category, "S001", "关系来源")
    owner.field_values = {field_key: second}
    owner.field_sources = {field_key: "second.txt"}
    owner.field_evidence = (
        GameObjectFieldEvidence(field_key, field_key, first, "first.txt", 40),
        GameObjectFieldEvidence(field_key, field_key, second, "second.txt", 40),
    )
    targets = (
        _object(target_category, first, "目标一"),
        _object(target_category, second, "目标二"),
    )
    md = _map(owner, *targets)

    # When: object-field relations are built.
    rows = tuple(row for row in object_field_relations(md) if row.kind is kind)

    # Then: neither variant is dropped and every row exposes the conflict.
    actual: set[str] = set()
    for row in rows:
        endpoint = row.item if target_category == "物品" else row.skill
        assert endpoint is not None
        actual.add(endpoint.object_id)
    assert actual == {first, second}
    assert {row.completeness for row in rows} == {RelationCompleteness.CONFLICT}


def test_recovered_drop_from_partial_doo_is_marked_partial() -> None:
    # Given: one valid unit drop survived a two-record placement table.
    monster = _object("单位", "n001", "掉落怪")
    item = _object("物品", "I001", "掉落装备")
    md = _map(monster, item)
    md.units = [
        Unit(
            "n001",
            0,
            0.0,
            0.0,
            0.0,
            0.0,
            serial=7,
            drop_sets=(DropSet(0, (DropEntry("I001", 100, 0, 0, 96),)),),
        )
    ]
    record_component_parse_issue(
        md,
        "preplaced",
        "war3mapUnits.doo",
        "recovered 1 of 2 placements",
    )

    # When: structural relations consume the recovered record.
    row = next(
        item
        for item in build_structural_item_relations(md)
        if item.kind is ItemRelationKind.UNIT_DROP
    )

    # Then: confirmed evidence remains, but completeness reflects lost siblings.
    assert row.completeness is RelationCompleteness.PARTIAL
    assert "recovered 1 of 2" in row.unresolved_reason


def test_object_field_failure_does_not_remove_unit_drop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: unit evidence is valid while the independent object-field channel fails.
    monster = _object("单位", "n001", "掉落怪")
    item = _object("物品", "I001", "掉落装备")
    md = _map(monster, item)
    md.units = [
        Unit(
            "n001",
            0,
            0.0,
            0.0,
            0.0,
            0.0,
            serial=7,
            drop_sets=(DropSet(0, (DropEntry("I001", 100, 0, 0, 96),)),),
        )
    ]

    def fail(_md: MapData):
        raise _RelationChannelFailure("object fields unavailable")

    monkeypatch.setattr(relation_builder, "object_field_relations", fail)

    # When: the complete relation index is built.
    index = build_item_relation_index(md)

    # Then: completed channels survive and the failed channel is diagnosed.
    assert index.for_kind(ItemRelationKind.UNIT_DROP)
    assert any(row.component == "item-relations" for row in md.diagnostics)


def _object(category: str, object_id: str, name: str) -> GameObject:
    return GameObject(
        category=category,
        ext="w3t" if category == "物品" else "w3u",
        obj_id=object_id,
        base_id=object_id,
        name=name,
        is_custom=True,
    )


def _map(*objects: GameObject) -> MapData:
    md = MapData("x.w3x", "关系韧性图")
    md.objects = {}
    for item in objects:
        md.objects.setdefault(item.category, []).append(item)
    md.obj_index = {item.obj_id: item for item in objects}
    md.obj_identity_index = {(item.category, item.obj_id): item for item in objects}
    return md
