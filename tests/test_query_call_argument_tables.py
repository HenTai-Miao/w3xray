"""Declared call arguments retain complete formulas and source-local positions."""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path

import pytest

from gametool import pack_query_cli as queries
from gametool.pack_query_options import PackQueryCliOptions

_FILE = "脚本调用参数索引.tsv"
_HEADER = [
    "来源",
    "行号",
    "函数",
    "调用",
    "参数序号",
    "参数",
    "字符串",
    "对象码",
    "机制",
    "用途",
    "摘要",
    "调用偏移",
]
_ENGLISH = [
    "source",
    "line",
    "function",
    "call",
    "argument_index",
    "argument",
    "string",
    "object_codes",
    "mechanism",
    "purpose",
    "summary",
    "call_offset",
]
_ORDER = [10, 5, 11, 7, 0, 9, 4, 1, 8, 6, 3, 2, 12]


def _rows(
    *, lua: bool = False, offset: str = "99", result: str = "I002"
) -> list[list[str]]:
    def code(value: str) -> str:
        return f"FourCC([=[{value}]=])" if lua else f"'{value}'"

    args = [code("I001"), "'+9007199254740993", code("ches"), "'-1", code(result)]
    return [
        [
            "war3map.lua" if lua else "war3map.j",
            "7",
            "Owner",
            "YDWENewItemsFormula",
            str(i),
            arg,
            "",
            "",
            "",
            "",
            "YDWENewItemsFormula(" if i == 1 else "",
            offset,
            f"扩展{i}",
        ]
        for i, arg in enumerate(args, 1)
    ]


def _write(pack: Path, rows: list[list[str]], *, bom: bool = False) -> Path:
    pack.mkdir(parents=True, exist_ok=True)
    path = pack / _FILE
    with path.open("w", encoding="utf-8-sig" if bom else "utf-8", newline="") as stream:
        csv.writer(stream, delimiter="\t").writerows(rows)
    return path


def _run(pack: Path, command: str, query: str):
    return queries.execute_pack_query(PackQueryCliOptions(str(pack), command, query))


@pytest.mark.parametrize("layout", ["canonical", "reordered", "english", "legacy"])
@pytest.mark.parametrize("lua", [False, True])
@pytest.mark.parametrize("bom", [False, True])
def test_structured_formulas_use_declared_columns_and_not_the_last_extra_cell(
    tmp_path: Path, layout: str, lua: bool, bom: bool
) -> None:
    rows = _rows(lua=lua)
    header = (_ENGLISH if layout == "english" else _HEADER) + ["扩展证据"]
    if layout in {"english", "reordered"}:
        rows = [
            [header[i] for i in _ORDER],
            *[[row[i] for i in _ORDER] for row in rows],
        ]
    elif layout == "canonical":
        rows.insert(0, header)
    path = _write(tmp_path, rows, bom=bom)
    before = path.read_bytes()
    assert queries.load_formulas(tmp_path) == [("I002", [("I001", 9007199254740993)])]
    result = _run(tmp_path, "recipe", "I002")
    assert result.exit_code == 0
    assert "9007199254740993" in result.render()
    assert not json.loads(result.render(as_json=True))["warnings"]
    assert path.read_bytes() == before


@pytest.mark.parametrize("reorder", [False, True])
def test_argument_only_header_does_not_require_a_summary_or_owner_function(
    tmp_path: Path, reorder: bool
) -> None:
    keep = [0, 1, 3, 4, 5, 11]
    if reorder:
        keep.reverse()
    _write(
        tmp_path,
        [[_HEADER[i] for i in keep], *[[row[i] for i in keep] for row in _rows()]],
    )
    assert queries.load_formulas(tmp_path) == [("I002", [("I001", 9007199254740993)])]


def test_interleaved_out_of_order_arguments_use_explicit_source_offsets(
    tmp_path: Path,
) -> None:
    first = _rows(offset="00099")
    second = _rows(offset="199", result="I003")
    _write(
        tmp_path,
        [
            _HEADER + ["扩展"],
            *[row for i in [4, 2, 0, 3, 1] for row in [first[i], second[i]]],
        ],
    )
    assert queries.load_formulas(tmp_path) == [
        ("I002", [("I001", 9007199254740993)]),
        ("I003", [("I001", 9007199254740993)]),
    ]


@pytest.mark.parametrize("problem", ["gap", "conflict", "owner"])
def test_incomplete_or_conflicting_argument_groups_never_become_partial_recipes(
    tmp_path: Path, problem: str
) -> None:
    rows = _rows()
    if problem == "gap":
        del rows[2]
    elif problem == "conflict":
        conflict = rows[1].copy()
        conflict[5] = "4"
        rows.append(conflict)
    else:
        rows[2][2] = "DifferentOwner"
    _write(tmp_path, [_HEADER + ["扩展"], *rows])
    result = _run(tmp_path, "recipe", "I002")
    assert result.exit_code == 2
    data = json.loads(result.render(as_json=True))
    assert data["warnings"] and _FILE in "\n".join(data["warnings"])
    assert "text" in result.render()


def test_identical_argument_mirrors_do_not_create_a_conflict_or_second_recipe(
    tmp_path: Path,
) -> None:
    rows = _rows()
    _write(tmp_path, [_HEADER + ["扩展"], *rows, *rows])
    assert queries.load_formulas(tmp_path) == [("I002", [("I001", 9007199254740993)])]
    result = _run(tmp_path, "recipe", "I002")
    assert not json.loads(result.render(as_json=True))["warnings"]


@pytest.mark.parametrize("problem", ["interrupted", "reordered"])
def test_no_offset_arguments_require_a_consecutive_unambiguous_run(
    tmp_path: Path, problem: str
) -> None:
    rows = _rows()
    for row in rows:
        row[10], row[11] = "YDWENewItemsFormula(", ""
    expected = []
    if problem == "interrupted":
        rows = [rows[0], *_rows(offset="199", result="I003"), *rows[1:]]
        expected = [("I003", [("I001", 9007199254740993)])]
    else:
        rows = [rows[i] for i in [0, 2, 1, 3, 4]]
    _write(tmp_path, [_HEADER + ["扩展"], *rows])
    assert queries.load_formulas(tmp_path) == expected
    result = _run(tmp_path, "recipe", "I002")
    assert result.exit_code == 2
    assert json.loads(result.render(as_json=True))["warnings"]


def test_one_offset_with_conflicting_callees_does_not_confirm_a_formula(
    tmp_path: Path,
) -> None:
    rows = _rows()
    other = rows[0].copy()
    other[3] = "OtherNative"
    _write(tmp_path, [_HEADER + ["扩展"], *rows, other])
    result = _run(tmp_path, "recipe", "I002")
    assert result.exit_code == 2
    assert "OtherNative" in result.render()
    assert json.loads(result.render(as_json=True))["warnings"]


def test_synth_does_not_claim_no_recipes_when_the_call_index_is_incomplete(
    tmp_path: Path,
) -> None:
    _write(tmp_path, [["来源", "摘要", "summary"], ["war3map.j", "first", "second"]])
    result = _run(tmp_path, "synth", "")
    assert result.exit_code == 2
    assert "本包无合成配方" not in result.render()
    assert "未找到可确认合成配方" in result.render()
    assert "text" in result.render()


@pytest.mark.parametrize("layout", ["canonical", "reordered", "english"])
def test_indexed_placements_keep_distinct_offsets_and_complete_summary(
    tmp_path: Path, layout: str
) -> None:
    rows = []
    for offset in ["99", "199"]:
        for i, arg in enumerate(["'I001'", "100", "200"], 1):
            rows.append(
                [
                    "war3map.j",
                    "1",
                    "Owner",
                    "CreateItem",
                    str(i),
                    arg,
                    "",
                    "",
                    "",
                    "",
                    "CreateItem('I001',100,200)" if i == 1 else "",
                    offset,
                    f"扩展{i}",
                ]
            )
    header = (_ENGLISH if layout == "english" else _HEADER) + ["扩展"]
    if layout in {"english", "reordered"}:
        rows = [
            [header[i] for i in _ORDER],
            *[[row[i] for i in _ORDER] for row in rows],
        ]
    else:
        rows.insert(0, header)
    _write(tmp_path, rows)
    assert queries.load_placements(tmp_path) == [("I001", 100.0, 200.0, "item")] * 2
    data = json.loads(_run(tmp_path, "near", "100 200 1").render(as_json=True))
    assert data["exit_code"] == 0 and not data["warnings"]
    assert data["entries"][0]["count"] == 2


@pytest.mark.parametrize("problem", ["duplicate", "missing", "short"])
@pytest.mark.parametrize("command", ["recipe", "near"])
def test_unclassifiable_call_index_discloses_the_source_and_recovery(
    tmp_path: Path, problem: str, command: str
) -> None:
    if problem == "duplicate":
        rows = [
            ["来源", "摘要", "summary"],
            [
                "war3map.j",
                "CreateItem('I001',100,200)",
                "YDWENewItemsFormula('I001',2,'I002')",
            ],
        ]
    elif problem == "missing":
        rows = [["来源", "行号", "函数"], ["war3map.j", "1", "YDWENewItemsFormula"]]
    else:
        rows = [["来源", "摘要"], ["war3map.j"]]
    _write(tmp_path, rows)
    result = _run(tmp_path, command, "I002" if command == "recipe" else "100 200 1")
    assert result.exit_code == 2
    assert json.loads(result.render(as_json=True))["warnings"]
    assert _FILE in result.render() and "text" in result.render()


def test_reordered_index_mirrors_do_not_promote_a_shadowed_lua_native(
    tmp_path: Path,
) -> None:
    scripts = tmp_path / "脚本可读文本"
    scripts.mkdir()
    (scripts / "war3map.lua").write_text(
        "local CreateItem = function(...) end\nCreateItem(FourCC('I001'),100,200)",
        encoding="utf-8",
    )
    row = [
        "war3map.lua",
        "2",
        "Owner",
        "CreateItem",
        "1",
        "FourCC('I001')",
        "",
        "",
        "",
        "",
        "CreateItem(FourCC('I001'),100,200)",
        "40",
        "扩展",
    ]
    header = _HEADER + ["扩展"]
    _write(tmp_path, [[header[i] for i in _ORDER], [row[i] for i in _ORDER]])
    assert queries.load_placements(tmp_path) == []


def test_cached_raw_rows_and_input_bytes_are_not_rewritten(tmp_path: Path) -> None:
    path = _write(tmp_path, [_HEADER + ["扩展"], *_rows()])
    before = path.read_bytes()
    raw = queries._read_rows(tmp_path, _FILE)
    snapshot = [row.copy() for row in raw]
    assert queries.load_formulas(tmp_path)
    assert raw == snapshot and queries._read_rows(tmp_path, _FILE) is raw
    assert path.read_bytes() == before


def test_same_size_mtime_call_edit_refreshes_formula_result(tmp_path: Path) -> None:
    path = _write(tmp_path, [_HEADER + ["扩展"], *_rows()])
    before = path.stat()
    assert queries.load_formulas(tmp_path)[0][0] == "I002"
    _write(tmp_path, [_HEADER + ["扩展"], *_rows(result="I003")])
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert path.stat().st_size == before.st_size
    assert queries.load_formulas(tmp_path)[0][0] == "I003"
