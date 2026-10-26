"""Spatial annotations retain the category of every relation endpoint."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pytest

from gametool import pack_query_cli as queries
from gametool.item_relation_exports import ACQUISITION_REPORT_HEADER
from gametool.pack_query_options import PackQueryCliOptions


@pytest.fixture(autouse=True)
def isolated_memo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")


def _write(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        csv.writer(stream, delimiter="\t", lineterminator="\n").writerows(rows)


def _relation(category: str, item: str, kind: str = "掉落") -> list[str]:
    row = [""] * len(ACQUISITION_REPORT_HEADER)
    row[:8] = ["relation", "map", kind, item, item, category, "X001", "来源"]
    return row


def _relations(pack: Path, rows: list[list[str]]) -> None:
    _write(pack / "掉落与获取关系.tsv", [list(ACQUISITION_REPORT_HEADER), *rows])


def _pack(pack: Path) -> Path:
    for category, objects in (
        ("单位", [("X001", "单位同码")]),
        ("可破坏物", [("X001", "可破坏物同码")]),
        (
            "物品",
            [("X001", "地面同码"), *[(f"I00{i}", f"产物{i}") for i in range(1, 5)]],
        ),
    ):
        _write(
            pack / "对象ID" / f"{category}.tsv",
            [
                ["分类", "ID", "数值", "基础ID", "名称", "自定义", "说明"],
                *[
                    [category, code, "1", code, name, "是", ""]
                    for code, name in objects
                ],
            ],
        )
    _write(
        pack / "对象字段.tsv",
        [
            ["分类", "ID", "名称", "字段键", "字段名", "值", "来源"],
            ["单位", "X001", "单位同码", "usei", "货架", "I003", "war3map.w3u"],
        ],
    )
    path = pack / "脚本可读文本" / "map.lua"
    path.parent.mkdir(parents=True)
    path.write_text(
        "CreateUnit(Player(0),FourCC('X001'),0,0,0)\n"
        "CreateItem(FourCC('X001'),0,0)\n"
        "CreateDestructable(FourCC('X001'),0,0,0,1,0)\n",
        encoding="utf-8",
    )
    _relations(
        pack,
        [
            _relation("单位", "I001", "怪物直接掉落"),
            _relation("可破坏物", "I002", "可破坏物掉落"),
            _relation("物品", "I004"),
        ],
    )
    return pack


def _near(pack: Path, *, limit: int = 0, kind: str = "") -> dict[str, Any]:
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(pack), "near", "0 0 1", limit=limit, near_kind=kind)
    )
    assert result.exit_code == 0
    return json.loads(result.render(as_json=True))


def test_native_categories_keep_distinct_drops_stock_names_and_positions(
    tmp_path: Path,
) -> None:
    data = _near(_pack(tmp_path))
    entries = {entry["kind"]: entry for entry in data["entries"]}
    assert set(entries) == {"脚本单位", "脚本物品", "脚本可破坏物"}
    for kind, name, item in (
        ("脚本单位", "单位同码", "I001"),
        ("脚本物品", "地面同码", "I004"),
        ("脚本可破坏物", "可破坏物同码", "I002"),
    ):
        entry = entries[kind]
        assert entry["name"] == name
        assert entry["drops"] == f"{item}[{item}]"
        assert entry["positions"] == [[0.0, 0.0]] and entry["count"] == 1
        assert bool(entry["sell"]) == (kind == "脚本单位")
    assert "I003" in entries["脚本单位"]["sell"]
    assert not data["warnings"]


@pytest.mark.parametrize(
    "category,kind,item,entry_kind",
    [
        ("unit", "掉落", "I001", "脚本单位"),
        (" UNITS ", "掉落", "I001", "脚本单位"),
        ("英雄", "怪物直接掉落", "I001", "脚本单位"),
        ("Heroes", "掉落", "I001", "脚本单位"),
        ("destructible", "掉落", "I002", "脚本可破坏物"),
        (" DESTRUCTABLES ", "掉落", "I002", "脚本可破坏物"),
        ("ITEMS", "掉落", "I004", "脚本物品"),
        ("", "怪物直接掉落", "I001", "脚本单位"),
        ("", "可破坏物掉落", "I002", "脚本可破坏物"),
        ("", "unit_drop", "I001", "脚本单位"),
        ("", "destructable_drop", "I002", "脚本可破坏物"),
    ],
)
def test_declared_categories_and_typed_legacy_kinds_select_one_identity(
    tmp_path: Path, category: str, kind: str, item: str, entry_kind: str
) -> None:
    _pack(tmp_path)
    row = _relation(category, item, kind)
    _relations(tmp_path, [row, row.copy()])
    data = _near(tmp_path)
    for entry in data["entries"]:
        assert entry["drops"] == (
            f"{item}[{item}]" if entry["kind"] == entry_kind else None
        )
    assert not data["warnings"]


@pytest.mark.parametrize("kind", ["单位", "物品", "装饰", "脚本"])
def test_explicit_filters_and_limits_preserve_category_qualified_annotations(
    tmp_path: Path, kind: str
) -> None:
    data = _near(_pack(tmp_path), limit=1, kind=kind)
    expected = {"脚本单位": "I001", "脚本物品": "I004", "脚本可破坏物": "I002"}
    for entry in data["entries"]:
        item = expected[entry["kind"]]
        assert entry["drops"] == f"{item}[{item}]"


def test_preplaced_items_and_destructables_never_inherit_unit_shop_stock(
    tmp_path: Path,
) -> None:
    _pack(tmp_path)
    _write(
        tmp_path / "预放置单位.tsv",
        [
            ["序号", "类型ID", "名称", "玩家", "X", "Y", "分类"],
            ["1", "X001", "地面同码", "0", "0", "0", "物品"],
        ],
    )
    _write(
        tmp_path / "预放置装饰物.tsv",
        [["序号", "类型ID", "名称", "X", "Y"], ["1", "X001", "可破坏物同码", "0", "0"]],
    )
    entries = {entry["kind"]: entry for entry in _near(tmp_path)["entries"]}
    assert entries["物品"]["sell"] is None and entries["装饰群"]["sell"] is None
    assert entries["物品"]["drops"] == "I004[I004]"
    assert entries["装饰群"]["drops"] == "I002[I002]"


@pytest.mark.parametrize(
    "category,kind,source,item",
    [
        ("", "掉落", "X001", "I001"),
        ("未确认类别", "掉落", "X001", "I001"),
        ("物品", "怪物直接掉落", "X001", "I001"),
        ("单位", "可破坏物掉落", "X001", "I001"),
        ("单位", "掉落", "invalid-source", "I001"),
        ("单位", "掉落", "X001", "invalid-item"),
    ],
)
def test_unresolved_identity_keeps_complete_diagnostics_without_false_annotation(
    tmp_path: Path, category: str, kind: str, source: str, item: str
) -> None:
    _pack(tmp_path)
    row = _relation(category, item, kind)
    row[6], row[22] = source, "完整证据\n末尾" + "证" * 5000
    _relations(tmp_path, [row])
    data = _near(tmp_path, limit=1)
    assert all(entry["drops"] is None for entry in data["entries"])
    assert len(data["warnings"]) == 1
    note = data["warnings"][0]
    assert (
        str(tmp_path) in note and "记录 2" in note and "drop" in note and "text" in note
    )
    assert json.dumps(row, ensure_ascii=False) in note


def test_nonspatial_source_category_never_binds_to_same_code_unit(
    tmp_path: Path,
) -> None:
    _pack(tmp_path)
    _relations(tmp_path, [_relation("技能", "I001")])
    data = _near(tmp_path)
    assert all(entry["drops"] is None for entry in data["entries"])
    assert not data["warnings"]


def test_script_unit_death_pool_only_augments_unit_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pack(tmp_path)
    monkeypatch.setattr(
        queries,
        "_unit_death_random_drops",
        lambda _script: [("X001", "Drops", [("I003", 1)])],
    )
    entries = {entry["kind"]: entry for entry in _near(tmp_path)["entries"]}
    assert entries["脚本单位"]["drops"] == "I001[I001]、产物3[I003]"
    assert entries["脚本可破坏物"]["drops"] == "I002[I002]"
    assert entries["脚本物品"]["drops"] == "I004[I004]"


def test_again_replays_category_qualified_annotations(tmp_path: Path) -> None:
    first = _near(_pack(tmp_path))
    replay = queries.execute_pack_query(PackQueryCliOptions(str(tmp_path), "again", ""))
    assert json.loads(replay.render(as_json=True))["entries"] == first["entries"]


def test_campaign_child_diagnostics_and_entries_keep_their_source(
    tmp_path: Path,
) -> None:
    pack = _pack(tmp_path / "子地图" / "first")
    damaged = _pack(tmp_path / "子地图" / "second")
    row = _relation("未知", "I001")
    _relations(damaged, [row])
    data = _near(tmp_path)
    assert data["section"] == "战役" and len(data["sections"]) == 2
    sections = {section["pack"]: section for section in data["sections"]}
    assert sections[str(pack)]["entries"][0]["drops"] == "I004[I004]"
    assert all(entry["drops"] is None for entry in sections[str(damaged)]["entries"])
    assert len(data["warnings"]) == 1 and str(damaged) in data["warnings"][0]


@pytest.mark.parametrize("code", ["!001", " 001", "Ä001"])
def test_full_four_byte_codes_are_preserved_without_stripping(
    tmp_path: Path, code: str
) -> None:
    _pack(tmp_path)
    script = tmp_path / "脚本可读文本" / "map.lua"
    script.write_text(
        script.read_text(encoding="utf-8").replace("X001", code), encoding="utf-8"
    )
    row = _relation("单位", "I001")
    row[6] = code
    _relations(tmp_path, [row])
    entries = _near(tmp_path)["entries"]
    assert all(entry["code"] == code for entry in entries)
    assert {entry["kind"]: entry["drops"] for entry in entries} == {
        "脚本单位": "I001[I001]",
        "脚本物品": None,
        "脚本可破坏物": None,
    }


def test_case_distinct_sources_never_share_drop_annotations(tmp_path: Path) -> None:
    _pack(tmp_path)
    script = tmp_path / "脚本可读文本" / "map.lua"
    with script.open("a", encoding="utf-8") as stream:
        stream.write("CreateUnit(Player(0),FourCC('x001'),0,0,0)\n")
    upper, lower = _relation("单位", "I001"), _relation("单位", "I002")
    lower[6] = "x001"
    _relations(tmp_path, [upper, lower])
    entries = {
        entry["code"]: entry for entry in _near(tmp_path, kind="单位")["entries"]
    }
    assert entries["X001"]["drops"] == "I001[I001]"
    assert entries["x001"]["drops"] == "I002[I002]"


def test_large_relation_group_is_complete_even_with_one_result_limit(
    tmp_path: Path,
) -> None:
    _pack(tmp_path)
    rows = [_relation("单位", f"{index:04X}") for index in range(2000)]
    rows.extend([_relation("可破坏物", "I002"), _relation("物品", "I004")])
    _relations(tmp_path, rows + rows)
    entries = {entry["kind"]: entry for entry in _near(tmp_path, limit=1)["entries"]}
    assert entries["脚本单位"]["drops"].split("、") == [
        f"{index:04X}[{index:04X}]" for index in range(2000)
    ]
    assert entries["脚本可破坏物"]["drops"] == "I002[I002]"
    assert entries["脚本物品"]["drops"] == "I004[I004]"
