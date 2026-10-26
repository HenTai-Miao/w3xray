"""Placement alternatives remain explicit evidence instead of a category guess."""

from __future__ import annotations

from dataclasses import asdict, replace
import json
from pathlib import Path

import pytest

from gametool import pack_query_cli as queries
from gametool.doo import Doodad, Unit
from gametool.doo_drops import DropEntry, DropSet
from gametool.guide_report import _drop_lines
from gametool.item_relation_builder import build_structural_item_relations
from gametool.item_relation_exports import format_item_acquisition_tsv
from gametool.item_relation_models import (
    ItemRelationIndex,
    ItemRelationKind,
    RelationCompleteness,
    RelationConfidence,
)
from gametool.knowledge_object_exports import write_object_ids
from gametool.knowledge_preplaced_exports import (
    format_preplaced_doodads_tsv,
    format_preplaced_units_tsv,
)
from gametool.map_data import GameObject, MapData
from gametool.pack_query_options import PackQueryCliOptions


@pytest.fixture(autouse=True)
def isolated_memo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")


def _map(
    categories: tuple[str, ...], *, decor: bool = False, indexes: bool = True
) -> MapData:
    md = MapData(path="read-only.w3x", name="分类关系")
    objects = [
        GameObject(category, "w3u", "X001", "X001", category + "来源", True)
        for category in categories
    ]
    objects += [
        GameObject("物品", "w3t", code, code, name, True)
        for code, name in [("I001", "掉落物品"), ("I002", "背包物品")]
    ]
    for obj in objects:
        md.objects.setdefault(obj.category, []).append(obj)
    if indexes:
        md.obj_index = {obj.obj_id: obj for obj in objects}
        md.obj_identity_index = {(obj.category, obj.obj_id): obj for obj in objects}
    groups = (DropSet(0, (DropEntry("I001", 70, 0, 0, 112),)),)
    if decor:
        md.doodads = [
            Doodad(
                "X001",
                0,
                1.25,
                -2.5,
                0.0,
                0.0,
                serial=17,
                source_offset=64,
                drop_sets=groups,
            )
        ]
    else:
        md.units = [
            Unit(
                "X001",
                0,
                1.25,
                -2.5,
                0.0,
                0.0,
                player=3,
                serial=17,
                source_offset=64,
                items=[(2, "I002")],
                drop_sets=groups,
            )
        ]
    return md


def _index(md: MapData) -> ItemRelationIndex:
    return ItemRelationIndex.build(build_structural_item_relations(md))


def _pack(md: MapData, pack: Path) -> None:
    pack.mkdir(parents=True, exist_ok=True)
    write_object_ids(md, str(pack / "对象ID"))
    (pack / "掉落与获取关系.tsv").write_text(
        format_item_acquisition_tsv(_index(md)), encoding="utf-8"
    )
    (pack / "预放置单位.tsv").write_text(
        format_preplaced_units_tsv(md), encoding="utf-8"
    )
    (pack / "预放置装饰物.tsv").write_text(
        format_preplaced_doodads_tsv(md), encoding="utf-8"
    )


def test_repeated_instances_keep_every_candidate_identity() -> None:
    md = _map(("单位", "物品"))
    md.units.append(replace(md.units[0], serial=18, source_offset=264))
    rows = _index(md).records
    assert len(rows) == 6 and {row.instance_serial for row in rows} == {17, 18}


def test_legacy_rawcode_winner_does_not_choose_between_candidate_categories() -> None:
    md = _map(("单位", "物品"))
    first = _index(md)
    md.obj_index["X001"] = md.objects["单位"][0]
    assert _index(md).records == first.records


def test_unknown_source_guide_is_one_explicit_uncertain_line() -> None:
    md = _map(())
    md.item_relations = _index(md)
    lines = _drop_lines(md)
    assert (
        len(lines) == 1 and "未确认预放置掉落线索" in lines[0] and "未解析" in lines[0]
    )


def test_confirmed_drop_annotation_remains_available(tmp_path: Path) -> None:
    md = _map(("单位",))
    _pack(md, tmp_path)
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "near", "1.25 -2.5 1")
    )
    entry = json.loads(result.render(as_json=True))["entries"][0]
    assert entry["drops"] == "掉落物品[I001]"


def test_unknown_item_name_does_not_hide_confirmed_structural_drop() -> None:
    md = _map(("单位",))
    md.objects["物品"] = [obj for obj in md.objects["物品"] if obj.obj_id != "I001"]
    md.obj_index.pop("I001")
    md.obj_identity_index.pop(("物品", "I001"))
    row = _index(md).for_kind(ItemRelationKind.UNIT_DROP)[0]
    assert row.item.name == "未解析" and row.item.object_id == "I001"
    assert (
        row.confidence is RelationConfidence.CONFIRMED
        and row.completeness is RelationCompleteness.UNRESOLVED
    )


def test_clue_flag_alone_never_becomes_a_confirmed_annotation(tmp_path: Path) -> None:
    md = _map(("单位",))
    _pack(md, tmp_path)
    drop = _index(md).for_kind(ItemRelationKind.UNIT_DROP)[0]
    clue = replace(
        drop,
        confidence=RelationConfidence.CLUE,
        completeness=RelationCompleteness.PARTIAL,
        unresolved_reason="完整依据" * 5000,
    )
    (tmp_path / "掉落与获取关系.tsv").write_text(
        format_item_acquisition_tsv(ItemRelationIndex.build([clue])), encoding="utf-8"
    )
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "near", "1.25 -2.5 1")
    )
    data = json.loads(result.render(as_json=True))
    assert data["entries"][0]["drops"] is None and len(data["warnings"]) == 1
    assert clue.unresolved_reason in data["warnings"][0]


@pytest.mark.parametrize("indexes", [False, True])
def test_unit_item_collision_keeps_ground_drop_and_inventory_as_conflicting_candidates(
    indexes: bool,
) -> None:
    md = _map(("单位", "物品"), indexes=indexes)
    rows = _index(md).records
    assert {row.kind for row in rows} == {
        ItemRelationKind.UNIT_DROP,
        ItemRelationKind.GROUND_PLACEMENT,
        ItemRelationKind.PREPLACED_INVENTORY,
    }
    assert len(rows) == 3
    assert all(
        row.completeness is RelationCompleteness.CONFLICT
        and row.confidence is RelationConfidence.CLUE
        for row in rows
    )
    assert all(
        "单位来源" in row.unresolved_reason and "物品来源" in row.unresolved_reason
        for row in rows
    )
    assert all((row.instance_serial, row.x, row.y) == (17, 1.25, -2.5) for row in rows)
    drop = next(row for row in rows if row.kind is ItemRelationKind.UNIT_DROP)
    inventory = next(
        row for row in rows if row.kind is ItemRelationKind.PREPLACED_INVENTORY
    )
    assert (drop.chance, drop.entry_index, drop.evidence.offset) == (70, 0, 112)
    assert inventory.slot == 2 and inventory.item.name == "背包物品"


@pytest.mark.parametrize("indexes", [False, True])
@pytest.mark.parametrize("category", ["单位", "物品"])
def test_unambiguous_unit_and_ground_item_relations_keep_their_own_meaning(
    category: str, indexes: bool
) -> None:
    rows = _index(_map((category,), indexes=indexes)).records
    if category == "单位":
        assert len(rows) == 2 and all(
            row.completeness is RelationCompleteness.COMPLETE for row in rows
        )
        assert all(row.confidence is RelationConfidence.CONFIRMED for row in rows)
    else:
        ground = next(
            row for row in rows if row.kind is ItemRelationKind.GROUND_PLACEMENT
        )
        assert (
            ground.completeness is RelationCompleteness.COMPLETE
            and ground.confidence is RelationConfidence.CONFIRMED
        )
        other = [
            row for row in rows if row.kind is not ItemRelationKind.GROUND_PLACEMENT
        ]
        assert len(other) == 2 and all(
            row.completeness is RelationCompleteness.CONFLICT
            and row.confidence is RelationConfidence.CLUE
            for row in other
        )


@pytest.mark.parametrize("indexes", [False, True])
def test_doodad_destructable_collision_does_not_promote_a_confirmed_drop(
    indexes: bool,
) -> None:
    md = _map(("装饰物", "可破坏物"), decor=True, indexes=indexes)
    rows = _index(md).records
    assert len(rows) == 1 and rows[0].kind is ItemRelationKind.DESTRUCTABLE_DROP
    assert (
        rows[0].completeness is RelationCompleteness.CONFLICT
        and rows[0].confidence is RelationConfidence.CLUE
    )
    assert (
        "装饰物来源" in rows[0].unresolved_reason
        and "可破坏物来源" in rows[0].unresolved_reason
    )


def test_unknown_source_retains_literal_drop_and_inventory_evidence_as_unresolved() -> (
    None
):
    rows = _index(_map(())).records
    assert len(rows) == 2
    assert all(
        row.completeness is RelationCompleteness.UNRESOLVED
        and row.confidence is RelationConfidence.CLUE
        for row in rows
    )
    assert {row.item.object_id for row in rows} == {"I001", "I002"}
    assert all(
        row.source is not None and row.source.object_id == "X001" for row in rows
    )


@pytest.mark.parametrize(
    "command,needle",
    [("where", "I001"), ("drop", "I001"), ("where", "I002"), ("drop", "X001")],
)
def test_queries_show_candidate_state_and_full_reason(
    tmp_path: Path, command: str, needle: str
) -> None:
    md = _map(("单位", "物品"))
    for objects in md.objects.values():
        for obj in objects:
            if obj.obj_id == "X001":
                obj.name += "完整" * 2000
    _pack(md, tmp_path)
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), command, needle, limit=1)
    )
    text = result.render()
    assert (
        result.exit_code == 0 and "候选" in text and "仅线索" in text and "冲突" in text
    )
    assert all(
        obj.name in text
        for objects in md.objects.values()
        for obj in objects
        if obj.obj_id == "X001"
    )


@pytest.mark.parametrize("decor", [False, True])
def test_near_does_not_treat_candidate_rows_as_confirmed_drop_annotations(
    tmp_path: Path, decor: bool
) -> None:
    md = _map(("装饰物", "可破坏物") if decor else ("单位", "物品"), decor=decor)
    _pack(md, tmp_path)
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "near", "1.25 -2.5 1")
    )
    data = json.loads(result.render(as_json=True))
    assert result.exit_code == 0 and data["entries"][0]["kind"] == "类别未确认"
    assert data["entries"][0]["drops"] is None and data["warnings"]
    assert any("仅线索" in note and "冲突" in note for note in data["warnings"])


@pytest.mark.parametrize("decor", [False, True])
def test_guide_keeps_uncertain_drop_as_explicit_located_evidence(decor: bool) -> None:
    md = _map(("装饰物", "可破坏物") if decor else ("单位", "物品"), decor=decor)
    md.item_relations = _index(md)
    lines = _drop_lines(md)
    assert len(lines) == 1
    text = "\n".join(lines)
    assert "未确认预放置掉落线索" in text and "I001" in text and "70" in text
    assert "1.25" in text and "-2.5" in text
    assert all(
        category + "来源" in text
        for category in (("装饰物", "可破坏物") if decor else ("单位", "物品"))
    )


def test_every_nested_candidate_survives_without_mutating_map_data() -> None:
    md = _map(("单位", "物品"))
    md.units[0].items = [(i, "I002") for i in range(4000)]
    md.units[0].drop_sets = (
        DropSet(0, tuple(DropEntry("I001", 70, 0, i, i * 8) for i in range(4000))),
    )
    before = (
        asdict(md.units[0]),
        {key: asdict(obj) for key, obj in md.obj_index.items()},
    )
    index = _index(md)
    assert len(index.records) == 8001
    assert len(index.for_kind(ItemRelationKind.PREPLACED_INVENTORY)) == 4000
    assert len(index.for_kind(ItemRelationKind.UNIT_DROP)) == 4000
    assert all(
        row.confidence is RelationConfidence.CLUE
        and row.completeness is RelationCompleteness.CONFLICT
        for row in index.records
    )
    assert (
        asdict(md.units[0]),
        {key: asdict(obj) for key, obj in md.obj_index.items()},
    ) == before
