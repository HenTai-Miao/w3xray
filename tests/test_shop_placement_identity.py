"""A confirmed shelf does not confirm an ambiguous unit/item position."""

from __future__ import annotations

import csv
from dataclasses import asdict
import json
from pathlib import Path

import pytest
from PIL import Image

from gametool import guide_minimap, pack_query_cli as queries
from gametool.doo import Unit
from gametool.guide_report import _shop_lines
from gametool.item_relation_fields import object_field_relations
from gametool.item_relation_exports import format_item_acquisition_tsv
from gametool.item_relation_models import (
    ItemRelationIndex,
    RelationCompleteness,
    RelationConfidence,
)
from gametool.knowledge_object_exports import write_object_ids
from gametool.knowledge_preplaced_exports import format_preplaced_units_tsv
from gametool.map_data import GameObject, MapData
from gametool.pack_query_options import PackQueryCliOptions
from gametool.placement_positions import unit_position_groups


@pytest.fixture(autouse=True)
def isolated_memo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")


def _map(
    *, collision: bool = True, kind: str = "Sellitems", indexes: bool = True
) -> MapData:
    md = MapData(path="read-only.w3x", name="商店位置")
    shop = GameObject(
        "单位",
        "w3u",
        "X001",
        "X001",
        "商店来源",
        True,
        field_values={kind: "I001"},
        field_sources={kind: "war3map.w3u"},
    )
    item = GameObject("物品", "w3t", "I001", "I001", "货物", True)
    md.objects = {"单位": [shop], "物品": [item]}
    if collision:
        md.objects["物品"].append(
            GameObject("物品", "w3t", "X001", "X001", "同码物品", True)
        )
    if indexes:
        objects = [obj for values in md.objects.values() for obj in values]
        md.obj_index = {obj.obj_id: obj for obj in objects}
        md.obj_identity_index = {(obj.category, obj.obj_id): obj for obj in objects}
    md.units = [
        Unit("X001", 0, 1.25, -2.5, 0.0, 0.0, serial=17),
        Unit("X001", 0, 10.25, -20.5, 0.0, 0.0, serial=18),
    ]
    return md


def _index(md: MapData) -> ItemRelationIndex:
    return ItemRelationIndex.build(object_field_relations(md))


def _pack(md: MapData, pack: Path) -> None:
    pack.mkdir(parents=True, exist_ok=True)
    write_object_ids(md, str(pack / "对象ID"))
    (pack / "预放置单位.tsv").write_text(
        format_preplaced_units_tsv(md), encoding="utf-8"
    )
    (pack / "掉落与获取关系.tsv").write_text(
        format_item_acquisition_tsv(_index(md)), encoding="utf-8"
    )
    with (pack / "对象字段.tsv").open("w", encoding="utf-8", newline="") as stream:
        csv.writer(stream, delimiter="\t").writerows(
            [
                ["分类", "ID", "名称", "字段键", "字段名", "值", "来源"],
                *[
                    [obj.category, obj.obj_id, obj.name, key, key, value, "map"]
                    for objects in md.objects.values()
                    for obj in objects
                    for key, value in obj.field_values.items()
                ],
            ]
        )


@pytest.mark.parametrize("indexes", [False, True])
@pytest.mark.parametrize("kind", ["Sellitems", "Makeitems"])
@pytest.mark.parametrize("collision", [False, True])
def test_shop_definition_and_instance_confidence_are_independent(
    indexes: bool, kind: str, collision: bool
) -> None:
    md = _map(collision=collision, kind=kind, indexes=indexes)
    rows = _index(md).records
    assert len(rows) == (3 if collision else 2)
    if collision:
        definition = [row for row in rows if row.instance_serial is None]
        candidates = [row for row in rows if row.instance_serial is not None]
        assert (
            len(definition) == 1
            and definition[0].confidence is RelationConfidence.CONFIRMED
        )
        assert (
            definition[0].completeness is RelationCompleteness.PARTIAL
            and definition[0].x is None
        )
        assert len(candidates) == 2 and all(
            row.confidence is RelationConfidence.CLUE
            and row.completeness is RelationCompleteness.CONFLICT
            for row in candidates
        )
        assert all(
            "商店来源" in row.unresolved_reason and "同码物品" in row.unresolved_reason
            for row in candidates
        )
    else:
        assert all(
            row.confidence is RelationConfidence.CONFIRMED
            and row.completeness is RelationCompleteness.COMPLETE
            for row in rows
        )
    assert all(row.item.name == "货物" for row in rows)


@pytest.mark.parametrize("kind", ["Sellitems", "Makeitems"])
def test_guide_shows_unlocated_shelf_and_each_candidate_without_confirming_coordinates(
    kind: str,
) -> None:
    md = _map(kind=kind)
    md.item_relations = _index(md)
    lines = _shop_lines(md)
    candidates = [line for line in lines if "未确认商店线索" in line]
    confirmed = [line for line in lines if "未确认商店线索" not in line]
    assert len(candidates) == 2 and len(confirmed) == 1 and "货物" in confirmed[0]
    assert "@" not in confirmed[0] and all(
        "仅线索" in line and "冲突" in line for line in candidates
    )
    assert any("1.25" in line and "-2.5" in line for line in candidates)
    assert any("10.25" in line and "-20.5" in line for line in candidates)


@pytest.mark.parametrize("kind", ["Sellitems", "Makeitems"])
def test_script_unit_coordinates_remain_available_beside_ambiguous_doo(
    kind: str,
) -> None:
    md = _map(kind=kind)
    md.scripts = {"map.lua": "CreateUnit(Player(0),FourCC('X001'),40,50,0)"}
    md.item_relations = _index(md)
    lines = _shop_lines(md, unit_position_groups(md))
    confirmed = [line for line in lines if "未确认商店线索" not in line]
    assert (
        len(confirmed) == 1
        and "@(40,50)" in confirmed[0]
        and "[脚本位置]" in confirmed[0]
    )
    assert "@(1.25,-2.5)" not in confirmed[0]


@pytest.mark.parametrize("kind", ["usei", "Sellitems", "Makeitems"])
def test_minimap_does_not_pin_ambiguous_objects_as_confirmed_shops(kind: str) -> None:
    md = _map(kind=kind)
    assert guide_minimap.shop_marks(md, unit_position_groups(md)) == ()


def test_minimap_keeps_explicit_script_unit_evidence_and_stock_aliases() -> None:
    md = _map(kind="Sellitems")
    md.scripts = {"map.lua": "CreateUnit(Player(0),FourCC('X001'),40,50,0)"}
    assert guide_minimap.shop_marks(md, unit_position_groups(md)) == (
        ("商店来源", 40.0, 50.0),
    )


@pytest.mark.parametrize("kind", ["Sellitems", "Makeitems"])
def test_shop_query_lists_stock_and_complete_candidate_position_evidence(
    tmp_path: Path, kind: str
) -> None:
    md = _map(kind=kind)
    _pack(md, tmp_path)
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "shop", "X001", limit=1)
    )
    text = result.render()
    assert (
        result.exit_code == 0 and "货物" in text and "仅线索" in text and "冲突" in text
    )
    assert "1.25" in text and "-2.5" in text and "10.25" in text and "-20.5" in text
    assert "商店来源" in text and "同码物品" in text


def test_confirmed_unit_position_filter_keeps_all_raw_evidence_by_default() -> None:
    md = _map()
    assert unit_position_groups(md)["X001"] == ((1.25, -2.5), (10.25, -20.5))
    assert unit_position_groups(md, confirmed_only=True) == {}


def test_minimap_explains_why_only_candidate_shops_cannot_be_pinned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    md = _map(kind="usei")
    monkeypatch.setattr(
        guide_minimap, "playable_bounds", lambda _md: (-100.0, -100.0, 100.0, 100.0)
    )
    monkeypatch.setattr(
        guide_minimap,
        "load_minimap_assets",
        lambda _md: (None, unit_position_groups(md)),
    )
    with pytest.raises(guide_minimap.GuideMinimapError, match="候选商店位置"):
        guide_minimap.write_guide_minimap(md, str(tmp_path / "marks.png"))


def test_large_candidate_position_set_and_source_data_are_preserved() -> None:
    md = _map()
    md.units = [
        Unit("X001", 0, float(i), -float(i), 0.0, 0.0, serial=i) for i in range(4000)
    ]
    original = [asdict(unit) for unit in md.units]
    rows = _index(md).records
    assert (
        len(rows) == 4001
        and sum(row.instance_serial is not None for row in rows) == 4000
    )
    md.item_relations = ItemRelationIndex.build(rows)
    assert len([line for line in _shop_lines(md) if "未确认商店线索" in line]) == 4000
    assert [asdict(unit) for unit in md.units] == original


def test_case_distinct_item_code_does_not_make_shop_positions_ambiguous() -> None:
    md = _map()
    other = md.objects["物品"][-1]
    other.obj_id = "x001"
    md.obj_index = {}
    md.obj_identity_index = {}
    assert all(
        row.completeness is RelationCompleteness.COMPLETE for row in _index(md).records
    )


def test_near_keeps_ambiguous_doo_unstocked_but_known_script_shop_stocked(
    tmp_path: Path,
) -> None:
    md = _map(kind="usei")
    _pack(md, tmp_path)
    scripts = tmp_path / "脚本可读文本"
    scripts.mkdir()
    (scripts / "map.lua").write_text(
        "CreateUnit(Player(0),FourCC('X001'),40,50,0)", encoding="utf-8"
    )
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "near", "0 0 100")
    )
    entries = json.loads(result.render(as_json=True))["entries"]
    assert any(e["kind"] == "类别未确认" and e["sell"] is None for e in entries)
    assert any(e["kind"] == "脚本单位" and "I001" in e["sell"] for e in entries)


def test_identical_serial_and_coordinates_keep_distinct_encoded_instances() -> None:
    md = _map()
    first, second = md.units
    first.source_offset = 64
    second.source_offset = 256
    second.serial, second.x, second.y = first.serial, first.x, first.y
    candidates = [row for row in _index(md).records if row.instance_serial is not None]
    assert len(candidates) == 2
    assert {row.evidence.location for row in candidates} == {
        "Sellitems；war3mapUnits.doo 实例17 @0x40",
        "Sellitems；war3mapUnits.doo 实例17 @0x100",
    }


@pytest.mark.parametrize("point", [("nan", "2"), ("1", "inf"), ("bad", "2"), ("", "2")])
def test_shop_retains_invalid_coordinate_records_as_full_diagnostics(
    tmp_path: Path, point: tuple[str, str]
) -> None:
    _pack(_map(collision=False), tmp_path)
    path = tmp_path / "掉落与获取关系.tsv"
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.reader(stream, delimiter="\t"))
    rows[1][10:12] = list(point)
    with path.open("w", encoding="utf-8", newline="") as stream:
        csv.writer(stream, delimiter="\t").writerows(rows)
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "shop", "X001")
    )
    data = json.loads(result.render(as_json=True))
    assert result.exit_code == 0 and "货物" in result.render()
    assert len(data["warnings"]) == 1
    assert json.dumps(rows[1], ensure_ascii=False) in data["warnings"][0]
    assert "坐标诊断" in result.render() and "@(nan" not in result.render()


@pytest.mark.parametrize("category", ["物品", "技能"])
def test_nonunit_stock_fields_do_not_create_shop_relations(category: str) -> None:
    md = _map(collision=False, indexes=False)
    shop = md.objects.pop("单位")[0]
    shop.category = category
    md.objects.setdefault(category, []).append(shop)
    original = asdict(shop)
    assert not _index(md).records
    assert asdict(shop) == original


def test_shadowed_script_factory_does_not_confirm_candidate_shop_coordinates() -> None:
    md = _map()
    md.scripts = {
        "map.lua": "local CreateUnit=function(...) end; CreateUnit(Player(0),FourCC('X001'),40,50,0)"
    }
    assert guide_minimap.shop_marks(md, unit_position_groups(md)) == ()
    assert unit_position_groups(md, confirmed_only=True) == {}


def test_minimap_includes_every_confirmed_manufacturing_shop_point() -> None:
    md = _map(collision=False, kind="Makeitems")
    assert guide_minimap.shop_marks(md, unit_position_groups(md)) == (
        ("商店来源", 1.25, -2.5),
        ("商店来源", 10.25, -20.5),
    )


def test_minimap_draws_script_shop_and_discloses_all_unconfirmed_points(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    md = _map()
    md.scripts = {"map.lua": "CreateUnit(Player(0),FourCC('X001'),40,50,0)"}
    monkeypatch.setattr(
        guide_minimap, "playable_bounds", lambda _md: (-100.0, -100.0, 100.0, 100.0)
    )
    monkeypatch.setattr(
        guide_minimap,
        "load_minimap_assets",
        lambda _md: (Image.new("RGB", (128, 128)), unit_position_groups(md)),
    )
    output = tmp_path / "marks.png"
    notes = guide_minimap.write_guide_minimap(md, str(output))
    assert output.is_file() and "商店 1" in "\n".join(notes)
    assert "2 处候选商店位置" in "\n".join(notes)


def test_additional_known_unit_points_do_not_claim_script_provenance() -> None:
    md = _map(collision=False)
    md.units = []
    md.item_relations = _index(md)
    lines = _shop_lines(md, {"X001": ((40.0, 50.0),)})
    assert len(lines) == 1 and "@(40,50)" in lines[0]
    assert "[位置证据]" in lines[0] and "[脚本位置]" not in lines[0]
