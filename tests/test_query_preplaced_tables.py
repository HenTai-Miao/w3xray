"""Complete preplaced records use declared columns and category evidence."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pytest

from gametool import pack_query_cli as queries
from gametool.pack_query_options import PackQueryCliOptions


@pytest.fixture(autouse=True)
def isolated_memo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")


def _write(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        csv.writer(stream, delimiter="\t", lineterminator="\n").writerows(rows)


def _objects(pack: Path, category: str, code: str = "X001") -> None:
    _write(
        pack / "对象ID" / f"{category}.tsv",
        [["分类", "ID", "名称"], [category, code, category + "名称"]],
    )


def _query(
    pack: Path,
    command: str = "near",
    query: str = "1.25 -2.5 1",
    *,
    limit: int = 0,
    expected: int = 0,
) -> dict[str, Any]:
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(pack), command, query, limit=limit)
    )
    assert result.exit_code == expected
    return json.loads(result.render(as_json=True))


@pytest.mark.parametrize("optional", ["name", "category"])
def test_missing_optional_field_keeps_confirmed_coordinates(
    tmp_path: Path, optional: str
) -> None:
    _write(
        tmp_path / "预放置单位.tsv",
        [["ID", "X", "Y", optional], ["X001", "1.25", "-2.5"]],
    )
    data = _query(tmp_path)
    assert data["entries"][0]["positions"] == [[1.25, -2.5]]
    assert len(data["spatial_diagnostics"]) == 1


@pytest.mark.parametrize("category", ["", "未知", "可破坏物"])
def test_unconfirmed_declared_category_preserves_point_without_annotation(
    tmp_path: Path, category: str
) -> None:
    _write(
        tmp_path / "预放置单位.tsv",
        [["ID", "X", "Y", "分类"], ["X001", "1.25", "-2.5", category]],
    )
    data = _query(tmp_path)
    assert data["entries"][0]["kind"] == "类别未确认"
    assert len(data["spatial_diagnostics"]) == 1


@pytest.mark.parametrize("code", ["!001", " 001", "Ä001"])
def test_headerless_four_byte_identity_keeps_every_character(
    tmp_path: Path, code: str
) -> None:
    _write(tmp_path / "预放置单位.tsv", [["1", code, "X", "1.25", "-2.5"]])
    assert _query(tmp_path)["entries"][0]["code"] == code


def test_malformed_legacy_prefix_does_not_hide_later_complete_record(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "预放置单位.tsv",
        [["malformed"], ["1", "X001", "首条有效", "1.25", "-2.5"]],
    )
    data = _query(tmp_path)
    assert data["entries"][0]["count"] == 1 and len(data["spatial_diagnostics"]) == 1


def test_many_headerless_instances_survive_explicit_group_limit(tmp_path: Path) -> None:
    _write(
        tmp_path / "预放置单位.tsv",
        [[str(i), "X001", "全部实例", "1.25", "-2.5"] for i in range(4000)],
    )
    entry = _query(tmp_path, limit=1)["entries"][0]
    assert entry["count"] == 4000 and entry["positions"] == [[1.25, -2.5]] * 4000


@pytest.mark.parametrize("decor", [False, True])
@pytest.mark.parametrize("headerless", [False, True])
def test_preplaced_table_keeps_first_record_and_both_axes(
    tmp_path: Path, decor: bool, headerless: bool
) -> None:
    header = (
        ["序号", "类型ID", "名称", "X", "Y"]
        if decor
        else ["序号", "类型ID", "名称", "玩家", "X", "Y", "Z"]
    )
    row = (
        ["1", "X001", "放置名称", "1.25", "-2.5"]
        if decor
        else ["1", "X001", "放置名称", "7", "1.25", "-2.5", "999"]
    )
    relative = "预放置装饰物.tsv" if decor else "预放置单位.tsv"
    _write(
        tmp_path / relative,
        ([header] if not headerless else []) + [row, ["2", *row[1:]]],
    )
    data = _query(tmp_path)
    assert len(data["entries"]) == 1
    assert data["entries"][0]["positions"] == [[1.25, -2.5], [1.25, -2.5]]
    assert data["entries"][0]["count"] == 2 and not data["spatial_diagnostics"]
    where = _query(tmp_path, "where", "X001")
    assert sum("(1.25, -2.5) [预放置]" in line for line in where["lines"]) == 2


def test_compact_legacy_unit_record_is_not_dropped(tmp_path: Path) -> None:
    _write(tmp_path / "预放置单位.tsv", [["1", "X001", "旧放置", "1.25", "-2.5"]])
    assert _query(tmp_path)["entries"][0]["positions"] == [[1.25, -2.5]]


@pytest.mark.parametrize("category", ["单位", "物品", "可破坏物", "装饰物"])
@pytest.mark.parametrize("english", [False, True])
def test_reordered_headers_follow_declared_identity_name_axes_and_category(
    tmp_path: Path, category: str, english: bool
) -> None:
    for table in ("单位", "物品", "可破坏物", "装饰物"):
        _objects(tmp_path, table)
    header = ["Y", "分类", "扩展", "名称", "类型ID", "X"]
    if english:
        header = ["y", "category", "extension", "object_name", "rawcode", "x"]
    relative = "预放置单位.tsv" if category in ("单位", "物品") else "预放置装饰物.tsv"
    _write(
        tmp_path / relative,
        [header, ["-2.5", category, "完整扩展", category + "名称", "X001", "1.25"]],
    )
    data = _query(tmp_path)
    entry = data["entries"][0]
    expected_kind = category if category in ("单位", "物品") else "装饰群"
    assert (entry["kind"], entry["name"], entry["positions"]) == (
        expected_kind,
        category + "名称",
        [[1.25, -2.5]],
    )
    assert not data["spatial_diagnostics"]
    text = "\n".join(_query(tmp_path, "where", category + "名称")["lines"])
    assert category + "名称" in text and "(1.25, -2.5) [预放置]" in text


@pytest.mark.parametrize(
    "bad_header",
    [
        ["序号", "类型ID", "名称", "X", "X", "Y"],
        ["序号", "类型ID", "名称", "X", "Y", "rawcode"],
        ["序号", "类型ID", "名称", "X", "Z"],
    ],
)
def test_ambiguous_or_missing_declared_roles_keep_full_schema_diagnostics(
    tmp_path: Path, bad_header: list[str]
) -> None:
    bad_header.append("扩展" + "尾" * 5000)
    row = ["1", "X001", "放置名称", "1.25", "-2.5", "123", "全文"]
    _write(tmp_path / "预放置单位.tsv", [bad_header, row])
    data = _query(tmp_path, expected=2)
    assert not data["entries"] and len(data["spatial_diagnostics"]) == 1
    note = data["spatial_diagnostics"][0]["message"]
    assert str(tmp_path) in note and "预放置单位.tsv" in note and "text" in note
    assert json.dumps(bad_header, ensure_ascii=False) in note
    where = _query(tmp_path, "where", "X001", expected=2)
    assert (
        len(where["warnings"]) == 1
        and json.dumps(bad_header, ensure_ascii=False) in where["warnings"][0]
    )


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "1e99999", "变量()"])
def test_invalid_numeric_records_are_diagnosed_without_hiding_confirmed_points(
    tmp_path: Path, value: str
) -> None:
    row = ["2", "X002", "不确认", value, "-2.5", "证据\n末尾" + "长" * 5000]
    _write(
        tmp_path / "预放置装饰物.tsv",
        [
            ["序号", "类型ID", "名称", "X", "Y", "额外"],
            ["1", "X001", "已确认", "1.25", "-2.5"],
            row,
        ],
    )
    data = _query(tmp_path, limit=1)
    assert [entry["code"] for entry in data["entries"]] == ["X001"]
    note = data["spatial_diagnostics"][0]["message"]
    assert "记录 3" in note and json.dumps(row, ensure_ascii=False) in note


def test_ambiguous_six_column_legacy_record_is_not_guessed(tmp_path: Path) -> None:
    row = ["1", "X001", "不明列位", "7", "1.25", "-2.5"]
    _write(tmp_path / "预放置单位.tsv", [row])
    data = _query(tmp_path, expected=2)
    assert not data["entries"] and data["spatial_diagnostics"]
    assert (
        json.dumps(row, ensure_ascii=False) in data["spatial_diagnostics"][0]["message"]
    )


@pytest.mark.parametrize("decor", [False, True])
def test_conflicting_object_categories_retain_unclassified_point_without_guessing(
    tmp_path: Path, decor: bool
) -> None:
    categories = ("可破坏物", "装饰物") if decor else ("单位", "物品")
    for category in categories:
        _objects(tmp_path, category)
    relative = "预放置装饰物.tsv" if decor else "预放置单位.tsv"
    _write(
        tmp_path / relative,
        [
            ["序号", "类型ID", "名称", "X", "Y"],
            ["1", "X001", "原始名称", "1.25", "-2.5"],
        ],
    )
    data = _query(tmp_path)
    entry = data["entries"][0]
    assert entry["kind"] == "类别未确认" and entry["name"] == "原始名称"
    assert (
        entry["positions"] == [[1.25, -2.5]]
        and entry["drops"] is None
        and entry["sell"] is None
    )
    assert len(data["spatial_diagnostics"]) == 1
    where = _query(tmp_path, "where", "原始名称")
    assert any("原始名称 (类别未确认)" in line for line in where["lines"])


def test_sparse_wide_schema_has_full_diagnostic_and_no_padding(tmp_path: Path) -> None:
    header = ["ID", "name", "X", *[f"extension-{i}" for i in range(20000)], "Y"]
    row = ["X001", "稀疏", "1.25"]
    _write(tmp_path / "预放置单位.tsv", [header, row])
    raw = queries._read_rows(tmp_path, "预放置单位.tsv")
    data = _query(tmp_path, expected=2)
    assert (
        not data["entries"]
        and json.dumps(row, ensure_ascii=False)
        in data["spatial_diagnostics"][0]["message"]
    )
    assert (
        raw == [header, row] and queries._read_rows(tmp_path, "预放置单位.tsv") is raw
    )


def test_campaign_diagnostic_only_child_and_again_keep_full_provenance(
    tmp_path: Path,
) -> None:
    good, bad = [tmp_path / "子地图" / name for name in ("001", "002")]
    _write(good / "预放置单位.tsv", [["1", "X001", "首条", "1.25", "-2.5"]])
    _write(
        bad / "预放置单位.tsv",
        [["ID", "X", "X", "Y"], ["X001", "1.25", "1.25", "-2.5"]],
    )
    data = _query(tmp_path, limit=1)
    assert data["section"] == "战役" and len(data["sections"]) == 2
    assert len(data["entries"]) == 1 and len(data["spatial_diagnostics"]) == 1
    assert data["spatial_diagnostics"][0]["pack"] == str(bad)
    replay = _query(tmp_path, "again", "")
    assert (
        replay["entries"] == data["entries"]
        and replay["spatial_diagnostics"] == data["spatial_diagnostics"]
    )
