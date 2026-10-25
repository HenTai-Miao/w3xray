"""Static spatial results follow getter values and complete helper contexts."""

import json
from pathlib import Path

import pytest

from gametool import pack_query_cli as queries
from gametool.map_data import MapData
from gametool.pack_query_options import PackQueryCliOptions
from gametool.pack_query_placements import script_placements
from gametool.placement_positions import script_position_groups
from gametool.script_call_argument_index import (
    build_script_call_argument_index,
    format_script_call_argument_index_tsv,
)
from gametool.script_function_graph import script_functions
from gametool.script_placement_analysis import analyze_script_placements

_LUA = "function Id() return FourCC('I001') end function X() return 12345.6787109375 end function Y() return -9876.5439453125 end "
_JASS = "function Id takes nothing returns integer\nreturn 'I001'\nendfunction\nfunction X takes nothing returns real\nreturn 12345.6787109375\nendfunction\nfunction Y takes nothing returns real\nreturn -9876.5439453125\nendfunction\n"
_POINT = (12345.6787109375, -9876.5439453125)


@pytest.mark.parametrize("lua", [True, False])
@pytest.mark.parametrize(
    "api,kind,unit",
    [
        ("CreateItem", "item", False),
        ("CreateItemLoc", "item", False),
        ("BlzCreateItemWithSkin", "item", False),
        ("CreateUnit", "unit", True),
        ("CreateUnitAtLoc", "unit", True),
        ("BlzCreateUnitWithSkin", "unit", True),
        ("CreateCorpse", "unit", True),
        ("CreateDestructable", "destructable", False),
        ("CreateDestructableZ", "destructable", False),
        ("CreateDeadDestructable", "destructable", False),
        ("CreateDeadDestructableZ", "destructable", False),
    ],
)
def test_getter_results_reach_every_native_placement_signature(
    lua: bool, api: str, kind: str, unit: bool
) -> None:
    coordinates = (
        "Location(X(),Y())"
        if api in {"CreateItemLoc", "CreateUnitAtLoc"}
        else "X(),Y()"
    )
    text = (
        (_LUA if lua else _JASS)
        + ("" if lua else "call ")
        + f"{api}({'Player(0),' if unit else ''}Id(),{coordinates})"
    )
    analysis = analyze_script_placements(text, lua=lua)
    assert [row.row() for row in analysis.placements] == [("I001", *_POINT, kind)]
    assert not analysis.diagnostics
    row = analysis.placements[0]
    assert text[row.offset : row.offset + len(row.expression)] == row.expression
    assert row.line == text.count("\n", 0, row.offset) + 1
    assert "Id;" in "\n".join(row.evidence) and "X;" in "\n".join(row.evidence)


@pytest.mark.parametrize("lua", [True, False])
def test_helper_parameters_use_real_call_contexts_in_both_languages(lua: bool) -> None:
    text = (
        "function Spawn(id,x,y) CreateItem(id,x,y) end Spawn(FourCC('I001'),1.25,-2.5)"
        if lua
        else "function Spawn takes integer id, real x, real y returns nothing\ncall CreateItem(id,x,y)\nendfunction\ncall Spawn('I001',1.25,-2.5)"
    )
    assert script_placements(text, lua=lua) == [("I001", 1.25, -2.5, "item")]


@pytest.mark.parametrize(
    "prefix,call",
    [
        ("Factory={}; function Factory.Spawn", "Factory.Spawn"),
        ("Factory={}; function Factory : Spawn", "Factory : Spawn"),
        ("local Spawn=function", "Spawn"),
    ],
)
def test_members_methods_and_anonymous_aliases_preserve_coordinate_parameters(
    prefix: str, call: str
) -> None:
    text = f"{prefix}(id,x,y) CreateItem(id,x,y) end {call}(FourCC('I001'),1.25,-2.5)"
    analysis = analyze_script_placements(text, lua=True)
    assert [row.row() for row in analysis.placements] == [("I001", 1.25, -2.5, "item")]
    assert not analysis.diagnostics
    assert "调用来源" in "\n".join(analysis.placements[0].evidence)


@pytest.mark.parametrize(
    "invocation",
    ["Spawn(Args())", "Spawn(table.unpack({Args()}))", "Spawn(select(2,0,Args()))"],
)
def test_multireturn_and_builtin_lists_reach_native_positions(invocation: str) -> None:
    text = (
        "function Args() return FourCC('I001'),1.25,-2.5 end function Spawn(...) CreateItem(...) end "
        + invocation
    )
    assert script_placements(text, lua=True) == [("I001", 1.25, -2.5, "item")]


def test_direct_native_multireturn_and_local_parallel_assignment() -> None:
    text = "function Args() return FourCC('I001'),1.25,-2.5 end CreateItem(Args()); local id,x,y=Args(); CreateItem(id,x,y)"
    assert script_placements(text, lua=True) == [("I001", 1.25, -2.5, "item")] * 2


def test_arithmetic_after_known_parameters_and_getters_keeps_float_precision() -> None:
    text = (
        _LUA
        + "function Spawn(id,x,y) CreateItem(id,x+0.125,Y()-0.25) end Spawn(Id(),X(),0)"
    )
    assert script_placements(text, lua=True) == [
        ("I001", _POINT[0] + 0.125, _POINT[1] - 0.25, "item")
    ]


def test_different_context_points_survive_while_mirrored_contexts_do_not_multiply() -> (
    None
):
    text = "function Spawn(id,x,y) CreateItem(id,x,y) end Spawn(FourCC('I001'),1,2); Spawn(FourCC('I001'),3,4); Spawn(FourCC('I001'),1,2)"
    assert script_placements(text, lua=True) == [
        ("I001", 1.0, 2.0, "item"),
        ("I001", 3.0, 4.0, "item"),
    ]
    assert not analyze_script_placements(text, lua=True).diagnostics


@pytest.mark.parametrize(
    "expression",
    ["Runtime()", "GetRandomReal(1,2)", "1e999", "nil", "'1.25'", "GetUnitX(u)"],
)
def test_unknown_coordinates_never_become_concrete_points(expression: str) -> None:
    text = f"CreateItem(FourCC('I001'),{expression},2)"
    analysis = analyze_script_placements(text, lua=True)
    assert not analysis.placements and len(analysis.diagnostics) == 1
    assert "坐标未静态确定" in analysis.diagnostics[0].reason


@pytest.mark.parametrize("expression", ["'I001'", "Runtime()", "FourCC('I001')+1"])
def test_text_or_dynamic_object_codes_are_not_promoted(expression: str) -> None:
    analysis = analyze_script_placements(f"CreateItem({expression},1,2)", lua=True)
    assert (
        not analysis.placements and "对象码未静态确定" in analysis.diagnostics[0].reason
    )


def test_known_and_unknown_invocations_keep_both_point_and_diagnostic() -> None:
    text = "function Spawn(id,x,y) CreateItem(id,x,y) end Spawn(FourCC('I001'),1,2); Spawn(FourCC('I001'),Runtime(),2)"
    analysis = analyze_script_placements(text, lua=True)
    assert [row.row() for row in analysis.placements] == [("I001", 1.0, 2.0, "item")]
    assert len(analysis.diagnostics) == 1


@pytest.mark.parametrize(
    "binding", ["local FourCC=function() return nil end;", "local _G={};"]
)
def test_redefined_code_or_global_table_is_not_treated_as_native(binding: str) -> None:
    native = "_G . CreateItem" if "_G" in binding else "CreateItem"
    assert not script_placements(binding + f" {native}(FourCC('I001'),1,2)", lua=True)


def test_ambiguous_helper_binding_does_not_supply_numeric_context() -> None:
    text = "function Spawn(id,x,y) CreateItem(id,x,y) end function Spawn(id,x,y) CreateItem(id,x,y) end Spawn(FourCC('I001'),1,2)"
    assert not script_placements(text, lua=True)


def test_runtime_location_handles_are_diagnosed_without_inventing_coordinates() -> None:
    text = "function Spawn(id,p) CreateItemLoc(id,p) end Spawn(FourCC('I001'),RuntimeLocation())"
    analysis = analyze_script_placements(text, lua=True)
    assert (
        not analysis.placements
        and "运行时" in analysis.diagnostics[0].reason
        and "未静态确定" in analysis.diagnostics[0].reason
    )


def test_deep_forwarding_and_source_graph_are_iterative_and_shared() -> None:
    depth = 1050
    text = (
        "\n".join(f"function F{i}(id,x,y) F{i + 1}(id,x,y) end" for i in range(depth))
        + f"\nfunction F{depth}(id,x,y) CreateItem(id,x,y) end F0(FourCC('I001'),1.25,-2.5)"
    )
    assert script_placements(text, lua=True) == [("I001", 1.25, -2.5, "item")]
    functions = script_functions(text, lua=True)
    assert not analyze_script_placements(text, lua=True).diagnostics
    assert functions.source_graph() is functions.source_graph()
    assert len(functions.source_graph().nodes) == 2 * (depth + 1) + 1


def test_thousands_of_parameter_points_have_no_context_ceiling() -> None:
    count = 1800
    text = "function Spawn(id,x,y) CreateItem(id,x,y) end " + ";".join(
        f"Spawn(FourCC('I001'),{i}.25,-{i}.5)" for i in range(count)
    )
    rows = script_placements(text, lua=True)
    assert len(rows) == count and rows[-1] == (
        "I001",
        count - 1 + 0.25,
        -(count - 1) - 0.5,
        "item",
    )


def test_recursive_variadic_contexts_terminate_without_losing_known_points() -> None:
    text = "function Spawn(...) CreateItem(...); Spawn(FourCC('I001'),1,2,...) end Spawn(FourCC('I002'),3,4)"
    assert {row[:3] for row in script_placements(text, lua=True)} == {
        ("I001", 1.0, 2.0),
        ("I002", 3.0, 4.0),
    }


def test_near_json_and_guide_groups_share_exact_context_points(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")
    text = "function Spawn(id,x,y) CreateUnit(Player(0),id,x,y,0) end Spawn(FourCC('n001'),12345.6787109375,-9876.5439453125)"
    scripts = tmp_path / "脚本可读文本"
    scripts.mkdir()
    (scripts / "war3map.lua").write_text(text, encoding="utf-8")
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "near", f"{_POINT[0]} {_POINT[1]} 1")
    )
    data = json.loads(result.render(as_json=True))
    entry = next(row for row in data["entries"] if row["code"] == "n001")
    assert (entry["x"], entry["y"], entry["dist"]) == (*_POINT, 0.0) and entry[
        "positions"
    ] == [list(_POINT)]
    md = MapData(path="synthetic.w3x", name="参数坐标", scripts={"war3map.lua": text})
    assert script_position_groups(md) == {"n001": (_POINT,)}


def test_near_miss_discloses_every_unresolved_source_site(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")
    text = (
        "CreateItem(FourCC('I001'),Runtime(),0); CreateItem(FourCC('I002'),Runtime(),1)"
    )
    scripts = tmp_path / "脚本可读文本"
    scripts.mkdir()
    (scripts / "war3map.lua").write_text(text, encoding="utf-8")
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "near", "0 0 1")
    )
    data = json.loads(result.render(as_json=True))
    assert not data["entries"]
    output = result.render()
    assert "2 条脚本点位诊断" in output and all(
        code in output for code in ("I001", "I002")
    )


def test_index_mirror_cannot_bypass_source_global_binding(tmp_path: Path) -> None:
    text = "local _G={}; _G . CreateItem(FourCC('I001'),1,2)"
    scripts = tmp_path / "脚本可读文本"
    scripts.mkdir()
    (scripts / "war3map.lua").write_text(text, encoding="utf-8")
    md = MapData(path="synthetic.w3x", name="原文上下文", scripts={"war3map.lua": text})
    (tmp_path / "脚本调用参数索引.tsv").write_text(
        format_script_call_argument_index_tsv(build_script_call_argument_index(md)),
        encoding="utf-8",
    )
    assert queries.load_placements(tmp_path) == []


def test_index_only_and_unmatched_legacy_calls_keep_full_coverage(
    tmp_path: Path,
) -> None:
    scripts = tmp_path / "脚本可读文本"
    scripts.mkdir()
    (scripts / "war3map.j").write_text("call CreateItem('I001',1,2)", encoding="utf-8")
    (tmp_path / "脚本调用参数索引.tsv").write_text(
        "war3map.j\t2\tCreateItem\tcall CreateItem('I002',3,4)\n", encoding="utf-8"
    )
    assert queries.load_placements(tmp_path) == [
        ("I001", 1.0, 2.0, "item"),
        ("I002", 3.0, 4.0, "item"),
    ]
