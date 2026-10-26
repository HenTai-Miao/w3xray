"""Reference queries retain declared identities, provenance and uncertainty."""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path

import pytest

from gametool import pack_query_cli as queries
from gametool.pack_query_options import PackQueryCliOptions

_FILE = "脚本对象码出现索引.tsv"
_HEADER = [
    "来源",
    "行号",
    "函数",
    "对象码",
    "10进制",
    "分类",
    "名称",
    "对象来源",
    "上下文",
    "机制",
    "摘要",
    "英文名",
    "细类",
    "源码偏移",
]
_ENGLISH = [
    "source",
    "line",
    "function",
    "rawcode",
    "decimal",
    "category",
    "name",
    "object_source",
    "context",
    "mechanism",
    "summary",
    "english_name",
    "subcategory",
    "source_offset",
]


def _row(code: str = "I001", *, consume: bool = False) -> list[str]:
    call = "GetItemTypeId" if consume else "CreateItem"
    return [
        "war3map.wct.txt",
        "37",
        "完整函数",
        code,
        "1227894833",
        "物品",
        "完整名称",
        "地图自定义",
        call,
        "ObjectCode",
        f"{call}('{code}') 完整摘要\n最后一行",
        "EnglishAlias",
        "装备",
        "1200",
    ]


def _write(pack: Path, rows: list[list[str]], *, bom: bool = False) -> Path:
    pack.mkdir(parents=True, exist_ok=True)
    path = pack / _FILE
    with path.open("w", encoding="utf-8-sig" if bom else "utf-8", newline="") as out:
        csv.writer(out, delimiter="\t").writerows(rows)
    return path


def _run(pack: Path, command: str, query: str = "I001", limit: int = 0):
    return queries.execute_pack_query(
        PackQueryCliOptions(str(pack), command, query, limit=limit)
    )


@pytest.mark.parametrize("command", ["refs", "locate"])
@pytest.mark.parametrize("layout", ["canonical", "reordered", "english", "legacy"])
@pytest.mark.parametrize("bom", [False, True])
def test_declared_reference_columns_and_first_legacy_record(
    tmp_path: Path, command: str, layout: str, bom: bool
) -> None:
    rows = [_row(), _row(consume=True)]
    order = [10, 13, 6, 1, 4, 12, 2, 8, 11, 5, 0, 9, 7, 3]
    if layout in {"reordered", "english"}:
        header = _ENGLISH if layout == "english" else _HEADER
        rows = [[header[i] for i in order], *[[r[i] for i in order] for r in rows]]
    elif layout == "canonical":
        rows.insert(0, _HEADER)
    path = _write(tmp_path, rows, bom=bom)
    before = path.read_bytes()
    result = _run(tmp_path, command)
    assert result.exit_code == 0
    assert not json.loads(result.render(as_json=True))["warnings"]
    text = result.render()
    if command == "refs":
        assert "共2处引用" in text
        assert "给予/创建: 1 处" in text
        assert "作为材料/触发媒介(被检测或移除): 1 处" in text
        assert "war3map.wct.txt:行37 完整函数" in text
        assert rows[-1][0] in text
        assert "最后一行" in text
    else:
        assert "I001: 2 处引用" in text
    assert path.read_bytes() == before


def test_refs_retains_every_provenance_and_extension_cell(tmp_path: Path) -> None:
    _write(
        tmp_path, [_HEADER + ["扩展证据", "扩展证据"], _row() + ["第一份", "末尾独有"]]
    )
    text = _run(tmp_path, "refs").render()
    for value in [
        "1227894833",
        "地图自定义",
        "CreateItem",
        "EnglishAlias",
        "装备",
        "1200",
        "第一份",
        "末尾独有",
    ]:
        assert value in text
    assert "第15列" in text and "第16列" in text


def test_refs_searches_every_confirmed_name_and_keeps_whole_group(
    tmp_path: Path,
) -> None:
    other = _row(consume=True)
    other[6] = "另一个记录名"
    other[11] = "DifferentAlias"
    _write(tmp_path, [_HEADER, _row(), other])
    text = _run(tmp_path, "refs", "DifferentAlias").render()
    assert "共2处引用" in text
    assert "给予/创建: 1 处" in text and "作为材料/触发媒介(被检测或移除): 1 处" in text
    assert "完整名称" in text and "另一个记录名" in text


@pytest.mark.parametrize("code", ["I001", "i001"])
def test_locate_does_not_merge_case_distinct_fourccs(tmp_path: Path, code: str) -> None:
    _write(tmp_path, [_HEADER, _row(code)])
    other = "i001" if code == "I001" else "I001"
    result = _run(tmp_path, "locate", other)
    assert result.exit_code == 2
    assert "缺少 " + other in result.render()
    assert _run(tmp_path, "locate", code).exit_code == 0


def test_locate_deduplicates_identical_codes_without_merging_case(
    tmp_path: Path,
) -> None:
    _write(tmp_path, [_HEADER, _row(), _row("i001"), _row("i001")])
    text = _run(tmp_path, "locate", "I001;I001;i001;I001").render()
    assert "命中全部 2 个特征码: I001、i001" in text
    assert "I001: 1 处引用" in text and "i001: 2 处引用" in text


@pytest.mark.parametrize("command", ["refs", "locate"])
def test_minimal_declared_code_records_are_not_discarded(
    tmp_path: Path, command: str
) -> None:
    _write(tmp_path, [["对象码", "来源"], ["I001", "独有来源.j"]])
    result = _run(tmp_path, command)
    assert result.exit_code == 0
    assert (
        "1处引用" in result.render()
        if command == "refs"
        else "1 处引用" in result.render()
    )


@pytest.mark.parametrize("command", ["refs", "locate"])
@pytest.mark.parametrize("problem", ["duplicate", "missing", "ambiguous"])
def test_invalid_schema_retains_recovery_and_never_guesses_identity(
    tmp_path: Path, command: str, problem: str
) -> None:
    if problem == "duplicate":
        rows = [["对象码", "rawcode", "名称"], ["I001", "I002", "完整名称"]]
    elif problem == "missing":
        rows = [["来源", "行号", "函数", "名称"], ["x.j", "1", "F", "I001"]]
    else:
        rows = [["不明字段", "内容"], ["I001", "完整名称"]]
    _write(tmp_path, rows)
    result = _run(tmp_path, command)
    data = json.loads(result.render(as_json=True))
    assert result.exit_code == 2
    assert data["warnings"] and _FILE in "\n".join(data["warnings"])
    assert "text" in result.render()
    assert "孤立对象" not in result.render() and "零消耗引用" not in result.render()


@pytest.mark.parametrize("command", ["refs", "locate"])
def test_partial_index_keeps_confirmed_rows_and_complete_diagnostics(
    tmp_path: Path, command: str
) -> None:
    _write(tmp_path, [_HEADER, _row(), ["不完整"], _row("汉字非法")])
    result = _run(tmp_path, command, limit=1)
    assert result.exit_code == 0
    text = result.render()
    assert "记录序号: 3, 4" in text
    assert "零消耗引用" not in text
    assert "至少" in text
    assert "text" in text
    assert "其余" not in text


def test_incomplete_locate_miss_is_unknown_not_proved_absent(tmp_path: Path) -> None:
    _write(tmp_path, [_HEADER, _row(), ["不完整"]])
    result = _run(tmp_path, "locate", "I001;I002")
    assert result.exit_code == 2
    assert "尚未确认 I002" in result.render()
    assert "缺少 I002" not in result.render()


@pytest.mark.parametrize("command", ["refs", "locate"])
def test_short_declared_rows_keep_confirmed_code_but_disclose_missing_evidence(
    tmp_path: Path, command: str
) -> None:
    _write(tmp_path, [_HEADER, _row(), _row()[:7]])
    result = _run(tmp_path, command)
    assert result.exit_code == 0
    text = result.render()
    assert "至少2处引用" in text if command == "refs" else "至少2 处已确认引用" in text
    assert "记录序号: 3" in text
    assert "零消耗引用" not in text


@pytest.mark.parametrize("command", ["refs", "locate"])
def test_ambiguous_first_record_never_silently_becomes_a_header(
    tmp_path: Path, command: str
) -> None:
    first = _row("code")
    first[1] = ""
    first[6] = "name"
    _write(tmp_path, [first, _row()])
    result = _run(tmp_path, command)
    assert result.exit_code == 2
    assert "首记录" in result.render() and "不明确" in result.render()
    assert "text" in result.render()


@pytest.mark.parametrize("code", ["A-!?", "é001", "code"])
@pytest.mark.parametrize("command", ["refs", "locate"])
def test_latin1_and_punctuation_codes_retain_exact_identity(
    tmp_path: Path, command: str, code: str
) -> None:
    _write(tmp_path, [_HEADER, _row(code)])
    assert _run(tmp_path, command, code).exit_code == 0


@pytest.mark.parametrize("command", ["refs", "locate"])
def test_diagnostic_only_campaign_scope_remains_visible(
    tmp_path: Path, command: str
) -> None:
    _write(tmp_path / "子地图" / "001_valid", [_HEADER, _row()])
    _write(
        tmp_path / "子地图" / "002_unknown", [["对象码", "rawcode"], ["I001", "I002"]]
    )
    result = _run(tmp_path, command)
    data = json.loads(result.render(as_json=True))
    assert result.exit_code == 0 and result.campaign
    assert "子地图 001_valid" in data["lines"][0]
    assert "子地图 002_unknown" in result.render()
    assert "002_unknown" in "\n".join(data["warnings"])


@pytest.mark.parametrize("limit", [0, 1, 2, 3])
def test_refs_limit_counts_complete_objects_and_preserves_every_occurrence(
    tmp_path: Path, limit: int
) -> None:
    _write(tmp_path, [_HEADER, _row(), _row(consume=True), _row("I002")])
    text = _run(tmp_path, "refs", "", limit).render()
    assert "共2处引用" in text and "GetItemTypeId('I001')" in text
    assert ("[I002]" in text) == (limit != 1)
    assert ("其余 1 条未显示" in text) == (limit == 1)


@pytest.mark.parametrize("command", ["refs", "locate"])
def test_same_size_mtime_source_change_refreshes_reference_identity(
    tmp_path: Path, command: str
) -> None:
    path = _write(tmp_path, [_HEADER, _row()])
    before = path.stat()
    assert _run(tmp_path, command).exit_code == 0
    _write(tmp_path, [_HEADER, _row("I002")])
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert path.stat().st_size == before.st_size
    assert _run(tmp_path, command, "I002").exit_code == 0
    assert "[I001]" not in _run(tmp_path, command, "I002").render()
