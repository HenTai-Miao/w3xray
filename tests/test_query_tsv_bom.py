"""UTF-8 signatures belong to table encoding, never to its first record."""

import csv
import json
import os
from pathlib import Path

import pytest

from gametool import pack_query_cli as queries
from gametool.pack_query_objects import OBJECT_TABLES
from gametool.pack_query_options import PackQueryCliOptions

_ID_HEADER = ["分类", "ID", "数值", "基础ID", "名称", "自定义", "说明"]
_FIELD_HEADER = ["分类", "ID", "名称", "字段键", "字段名", "值", "来源"]
_LAYOUTS = ("headerless", "header", "quoted-headerless", "quoted-header")
_COMMANDS = {"单位": "units", "技能": "skills", "英雄": "heroes", "增益": "buffs"}


@pytest.fixture(autouse=True)
def isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")


def _write(
    path: Path,
    rows: list[list[str]],
    *,
    quoted: bool = False,
    encoding: str = "utf-8-sig",
) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding=encoding, newline="") as handle:
        csv.writer(
            handle,
            delimiter="\t",
            lineterminator="\n",
            quoting=csv.QUOTE_ALL if quoted else csv.QUOTE_MINIMAL,
        ).writerows(rows)
    return path.read_bytes()


def _run(pack: Path, command: str, query: str):
    return queries.execute_pack_query(PackQueryCliOptions(str(pack), command, query))


@pytest.mark.parametrize("table", OBJECT_TABLES)
@pytest.mark.parametrize("layout", _LAYOUTS)
def test_bom_preserves_first_object_and_complete_counts(
    tmp_path: Path, table: str, layout: str
) -> None:
    rows = [
        [table, "X001", "123", "hfoo", "首条对象", "是", "完整\n\t首说明"],
        [table, "X002", "456", "hfoo", "末条对象", "否", "完整末说明"],
    ]
    if layout.endswith("header"):
        rows.insert(0, _ID_HEADER)
    path = tmp_path / "对象ID" / f"{table}.tsv"
    before = _write(path, rows, quoted=layout.startswith("quoted"))
    view = queries._named_table(tmp_path, f"对象ID/{table}.tsv", table)
    assert view.complete
    assert [row[1] for row in view.rows[1:]] == ["X001", "X002"]
    for command, term in [("search", table + ":X001"), ("list", table)]:
        result = _run(tmp_path, command, term)
        assert result.exit_code == 0 and "首条对象" in result.render()
        assert not json.loads(result.render(as_json=True))["warnings"]
    if table in _COMMANDS:
        result = _run(tmp_path, _COMMANDS[table], "X001")
        assert result.exit_code == 0 and "首说明" in result.render()
    assert path.read_bytes() == before


@pytest.mark.parametrize("table", OBJECT_TABLES)
@pytest.mark.parametrize("layout", _LAYOUTS)
def test_bom_preserves_first_field_and_field_only_identity(
    tmp_path: Path, table: str, layout: str
) -> None:
    rows = [
        [table, "X001", "首条对象", "DataA:1", "首字段", "首\n\t字段值", "map.w3a"],
        [table, "X002", "末条对象", "DataB:1", "末字段", "末字段值", "map.w3a"],
    ]
    if layout.endswith("header"):
        rows.insert(0, _FIELD_HEADER)
    path = tmp_path / "对象字段.tsv"
    before = _write(path, rows, quoted=layout.startswith("quoted"))
    view = queries._named_table(tmp_path, path.name)
    assert view.complete
    assert [row[1] for row in view.rows[1:]] == ["X001", "X002"]
    assert view.rows[1][5] == "首\n\t字段值"
    if table in _COMMANDS:
        result = _run(tmp_path, _COMMANDS[table], "X001")
        assert result.exit_code == 0 and "首\n\t字段值" in result.render()
        assert "由对象字段.tsv确认" in result.render()
        assert not json.loads(result.render(as_json=True))["warnings"]
    assert path.read_bytes() == before


@pytest.mark.parametrize("header", [False, True])
@pytest.mark.parametrize("quoted", [False, True])
def test_call_index_retains_source_summary_offset_and_first_call(
    tmp_path: Path, header: bool, quoted: bool
) -> None:
    source = '目录/首\t份\n"脚本".j'
    summary = "CreateItem('I001',100,200)"
    if header:
        rows = [
            ["来源", "行号", "函数", "类型", "参数序号", "参数", "摘要", "调用偏移"],
            [source, "12", "CreateItem", "arg", "1", "'I001'", summary, "987654"],
        ]
    else:
        rows = [[source, "12", "CreateItem", "1", summary]]
    path = tmp_path / "脚本调用参数索引.tsv"
    before = _write(path, rows, quoted=quoted)
    entries = queries._call_argument_rows(tmp_path)
    assert len(entries) == 1
    row, actual_summary, offset = entries[0]
    assert row[0] == source and actual_summary == summary
    assert offset == ("987654" if header else "")
    assert queries._indexed_call_identity(row, actual_summary, offset) == (
        (source, offset) if header else (source, "12", summary)
    )
    assert path.read_bytes() == before


@pytest.mark.parametrize("source", ["war3map.j", "war3map.lua"])
@pytest.mark.parametrize("quoted", [False, True])
def test_index_only_coordinates_and_recipes_use_complete_declared_columns(
    tmp_path: Path, source: str, quoted: bool
) -> None:
    header = ["来源", "行号", "函数", "类型", "参数序号", "参数", "摘要", "调用偏移"]
    code = "FourCC('I001')" if source.endswith(".lua") else "'I001'"
    formula = (
        "YDWENewItemsFormula(FourCC('I001'),4,FourCC('ches'),0,FourCC('I002'))"
        if source.endswith(".lua")
        else "call YDWENewItemsFormula('I001',4,'ches',0,'I002')"
    )
    path = tmp_path / "脚本调用参数索引.tsv"
    before = _write(
        path,
        [
            header,
            [
                source,
                "1",
                "CreateItem",
                "arg",
                "1",
                code,
                f"CreateItem({code},100,200)",
                "99",
            ],
            [source, "2", "YDWENewItemsFormula", "arg", "1", code, formula, "199"],
        ],
        quoted=quoted,
    )
    assert queries.load_placements(tmp_path) == [("I001", 100.0, 200.0, "item")]
    assert queries.load_formulas(tmp_path) == [("I002", [("I001", 4)])]
    result = _run(tmp_path, "near", "100 200 1")
    payload = json.loads(result.render(as_json=True))
    assert result.exit_code == 0
    assert [(row["code"], row["x"], row["y"]) for row in payload["entries"]] == [
        ("I001", 100, 200)
    ]
    assert not payload["warnings"]
    result = _run(tmp_path, "recipe", "I002")
    assert result.exit_code == 0 and "I001" in result.render()
    assert path.read_bytes() == before


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig"])
def test_only_file_signature_is_consumed_and_full_csv_values_survive(
    tmp_path: Path, encoding: str
) -> None:
    value = '\ufeff正文\t"完整"\r\n内\ufeff嵌\n' * 20_000 + "最后一个字"
    rows = [["来源", "摘要"], ["\ufeff真实来源.j", value], ["另一个.j", "\ufeff尾部"]]
    path = tmp_path / "原文.tsv"
    previous_limit = csv.field_size_limit()
    before = _write(path, rows, encoding=encoding)
    assert queries._read_rows(tmp_path, path.name) == rows
    assert csv.field_size_limit() == previous_limit
    assert queries._read_rows(tmp_path, path.name) == rows
    assert path.read_bytes() == before


def test_second_leading_signature_is_literal_first_cell_data(tmp_path: Path) -> None:
    rows = [["\ufeff真实来源.j", "保留字符"], ["末行", "内\ufeff嵌"]]
    path = tmp_path / "原文.tsv"
    _write(path, rows)
    assert queries._read_rows(tmp_path, path.name) == rows


@pytest.mark.parametrize("command", ["stats", "quest", "text"])
def test_line_based_table_queries_consume_only_one_file_signature(
    tmp_path: Path, command: str
) -> None:
    filename = "地图信息.txt" if command == "stats" else "脚本字符串索引.tsv"
    text = "war3map.j\t1\tCreateQuestBJ\t任务\ufeff正文\n尾部原文\n"
    path = tmp_path / filename
    path.write_text(text, encoding="utf-8-sig")
    assert "".join(queries._iter_tsv_lines(path)) == text
    result = _run(tmp_path, command, "" if command == "stats" else "任务")
    assert result.exit_code == 0
    assert "任务\ufeff正文" in result.render()
    assert "\ufeffwar3map.j" not in result.render()


def test_bom_only_file_is_an_empty_table_not_a_data_record(tmp_path: Path) -> None:
    path = tmp_path / "空.tsv"
    path.write_bytes(b"\xef\xbb\xbf")
    assert queries._read_rows(tmp_path, path.name) == []
    assert list(queries._iter_tsv_lines(path)) == []


@pytest.mark.parametrize("signature", [b"", b"\xef\xbb\xbf"])
def test_invalid_utf8_keeps_source_diagnostics(
    tmp_path: Path, signature: bytes
) -> None:
    path = tmp_path / "对象ID" / "单位.tsv"
    path.parent.mkdir()
    path.write_bytes(signature + "单位\tX001\t1\thfoo\t".encode() + b"\xff\n")
    result = _run(tmp_path, "units", "X001")
    assert (
        result.exit_code == 2
        and not queries._named_table(tmp_path, "对象ID/单位.tsv", "单位").complete
    )
    assert json.loads(result.render(as_json=True))["warnings"]
    assert "对象ID/单位.tsv" in result.render()


def test_bom_changes_keep_raw_byte_freshness_with_same_size_and_mtime(
    tmp_path: Path,
) -> None:
    path = tmp_path / "对象ID" / "单位.tsv"
    row = ["单位", "X001", "1", "hfoo", "甲", "是", "描述"]
    _write(path, [row])
    before = path.stat()
    first = queries._read_rows(tmp_path, "对象ID/单位.tsv")
    assert first == [row]
    assert queries._read_rows(tmp_path, "对象ID/单位.tsv") is first
    row[4] = "甲乙"
    _write(path, [row], encoding="utf-8")
    assert path.stat().st_size == before.st_size
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert queries._read_rows(tmp_path, "对象ID/单位.tsv") == [row]
    result = _run(tmp_path, "units", "X001")
    assert "[X001] 甲乙" in result.render() and result.exit_code == 0
    row[4] = "甲"
    _write(path, [row])
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert queries._read_rows(tmp_path, "对象ID/单位.tsv") == [row]


def test_multiline_first_record_keeps_logical_diagnostic_indices(
    tmp_path: Path,
) -> None:
    rows = [
        ["单位", "X001", "1", "hfoo", "首\n" * 5_000, "是", "首项"],
        ["单位", "不是四码", "2", "hfoo", "损坏", "是", "损坏"],
        ["单位", "X003", "3", "hfoo", "末项", "是", "末项"],
    ]
    _write(tmp_path / "对象ID" / "单位.tsv", rows, quoted=True)
    view = queries._named_table(tmp_path, "对象ID/单位.tsv", "单位")
    assert [row[1] for row in view.rows[1:]] == ["X001", "X003"]
    assert "记录序号: 2；" in view.diagnostics[0]


def test_diff_first_object_is_complete_with_mixed_bom_encodings(tmp_path: Path) -> None:
    old, new = tmp_path / "old", tmp_path / "new"
    row = ["单位", "X001", "1", "hfoo", "旧名称", "是", "完整首项"]
    _write(old / "对象ID" / "单位.tsv", [row])
    _write(
        new / "对象ID" / "单位.tsv",
        [[*row[:4], "新名称", *row[5:]]],
        encoding="utf-8",
    )
    result = _run(new, "diff", str(old))
    assert result.exit_code == 0 and result.comparison_complete
    assert result.has_changes
    assert "~ [X001] 新名称" in result.render()
    assert queries.load_units(old) == {"X001": "旧名称"}
    assert not json.loads(result.render(as_json=True))["warnings"]


@pytest.mark.parametrize("table,command", _COMMANDS.items())
def test_campaign_first_records_survive_in_each_source_kind(
    tmp_path: Path, table: str, command: str
) -> None:
    for child in ("001", "002"):
        pack = tmp_path / "子地图" / child
        if child == "001":
            path = pack / "对象ID" / f"{table}.tsv"
            rows = [[table, "X001", "1", "hfoo", "首项" + child, "是", "完整说明"]]
        else:
            path = pack / "对象字段.tsv"
            rows = [[table, "X001", "首项" + child, "DataA", "字段", "完整值", "map"]]
        _write(path, rows)
    result = _run(tmp_path, command, "X001")
    assert result.exit_code == 0 and result.campaign
    assert len(result.sections) == 2
    assert "首项001" in result.render() and "首项002" in result.render()
    assert not json.loads(result.render(as_json=True))["warnings"]
