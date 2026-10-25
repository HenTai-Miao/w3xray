"""Lua free names follow lexical _ENV; uncertain environments never become points."""

import json
from pathlib import Path

import pytest

from gametool import pack_query_cli as queries
from gametool.map_data import MapData
from gametool.pack_query_options import PackQueryCliOptions
from gametool.pack_query_placement_index import indexed_placements
from gametool.pack_query_placements import script_placements, script_rectangles
from gametool.placement_positions import script_position_groups
from gametool.script_function_graph import script_functions
from gametool.script_function_bindings import ScriptFunctionBindings
from gametool.script_placement_analysis import analyze_script_placements
from gametool.script_rectangle_analysis import analyze_script_rectangles
from gametool.script_sources import AnalysisScriptSource


@pytest.mark.parametrize(
    "binding",
    [
        "local _ENV={}",
        "_ENV={}",
        "local _ENV=RuntimeTable()",
        "local _ENV=nil",
        "local _ENV=0",
        "local _ENV=function()end",
        "function _ENV()end",
        "local function _ENV()end",
    ],
)
@pytest.mark.parametrize("prefix", ["", "_ENV.", "_G."])
def test_private_or_unresolved_environment_is_never_assumed_native(
    binding: str, prefix: str
) -> None:
    source = f"{binding};{prefix}CreateItem(FourCC('I001'),1,2);gg_rct_A=Rect(0,0,2,4)"
    points = analyze_script_placements(source, lua=True)
    regions = analyze_script_rectangles(source, lua=True)
    assert not points.placements and not regions.rectangles
    assert len(points.diagnostics) == len(regions.diagnostics) == 1
    assert "_ENV" in points.diagnostics[0].reason
    assert "_ENV" in regions.diagnostics[0].reason
    assert points.diagnostics[0].expression.startswith(prefix + "CreateItem")


@pytest.mark.parametrize(
    "binding",
    [
        "_ENV=_ENV",
        "_ENV=_G",
        "local _ENV=_ENV",
        "local _ENV=_G",
        "local G=_G;local _ENV=G",
        "local G=_ENV;local _ENV=G",
        "Global=_G;local _ENV=Global",
        "local G=_G;_ENV={};_ENV=G",
        "local G=_G;local _ENV={};_ENV=G",
        "local _ENV,unused=_G,123",
    ],
)
@pytest.mark.parametrize("prefix", ["", "_ENV."])
def test_proved_standard_environment_aliases_keep_complete_geometry(
    binding: str, prefix: str
) -> None:
    source = f"{binding};{prefix}CreateItem({prefix}FourCC('I001'),1,2);{prefix}gg_rct_A={prefix}Rect(0,0,2,4)"
    assert script_placements(source, lua=True) == [("I001", 1.0, 2.0, "item")]
    assert script_rectangles(source, lua=True) == [("gg_rct_A", 0.0, 0.0, 2.0, 4.0)]


@pytest.mark.parametrize("parameter", ["_ENV", "other,_ENV"])
def test_environment_parameters_are_lexical_and_do_not_leak_between_functions(
    parameter: str,
) -> None:
    source = f"function Private({parameter})CreateItem(FourCC('I001'),1,2)end function Normal()CreateItem(FourCC('I002'),3,4)end;Normal()"
    analysis = analyze_script_placements(source, lua=True)
    assert [row.row() for row in analysis.placements] == [("I002", 3.0, 4.0, "item")]
    assert len(analysis.diagnostics) == 1 and "_ENV" in analysis.diagnostics[0].reason


def test_private_environment_field_does_not_replace_outer_geometry() -> None:
    source = "local Make=Rect;gg_rct_A=Make(0,0,2,4);do local _ENV={};gg_rct_A=Make(10,20,30,40)end;CreateItemLoc(FourCC('I001'),GetRectCenter(gg_rct_A))"
    assert script_placements(source, lua=True) == [("I001", 1.0, 2.0, "item")]
    assert len(script_rectangles(source, lua=True)) == 2


@pytest.mark.parametrize("outer", ["", "E={};"])
def test_private_environment_alias_write_never_becomes_an_outer_global(
    outer: str,
) -> None:
    source = (
        outer
        + "local G=_G;local _ENV={};E=G;_ENV=G;local _ENV=E;CreateItem(FourCC('I001'),1,2);gg_rct_A=Rect(0,0,2,4)"
    )
    points = analyze_script_placements(source, lua=True)
    regions = analyze_script_rectangles(source, lua=True)
    assert not points.placements and not regions.rectangles
    assert "_ENV" in points.diagnostics[0].reason
    assert "_ENV" in regions.diagnostics[0].reason


def test_nested_environment_restoration_preserves_the_outer_private_scope() -> None:
    source = "local G=_G;local _ENV={};do local _ENV=G;CreateItem(FourCC('I001'),1,2)end;CreateItem(FourCC('I002'),3,4)"
    analysis = analyze_script_placements(source, lua=True)
    assert [row.row() for row in analysis.placements] == [("I001", 1.0, 2.0, "item")]
    assert (
        len(analysis.diagnostics) == 1 and "I002" in analysis.diagnostics[0].expression
    )


def test_local_initializer_reads_the_preceding_environment() -> None:
    source = "local _ENV={};local _ENV=_ENV;CreateItem(FourCC('I001'),1,2)"
    assert not script_placements(source, lua=True)


@pytest.mark.parametrize(
    "definition",
    [
        "function Rect(a,b,c,d)return Make(a,b,c,d)end",
        "function _ENV.Rect(a,b,c,d)return Make(a,b,c,d)end",
    ],
)
def test_source_functions_and_saved_native_aliases_inside_private_environment(
    definition: str,
) -> None:
    source = f"local Make=Rect;local _ENV={{}};{definition};gg_rct_A=Rect(0,0,2,4)"
    assert script_rectangles(source, lua=True) == [("gg_rct_A", 0.0, 0.0, 2.0, 4.0)]


def test_explicit_environment_members_bypass_same_named_locals() -> None:
    source = "local Rect=Runtime;local FourCC=Runtime;_ENV.gg_rct_甲=_ENV.Rect(0,0,2,4);_ENV.CreateItem(_ENV.FourCC('I001'),_ENV.GetRectCenterX(_ENV.gg_rct_甲),_ENV.GetRectCenterY(_ENV.gg_rct_甲))"
    assert script_placements(source, lua=True) == [("I001", 1.0, 2.0, "item")]
    assert script_rectangles(source, lua=True) == [("gg_rct_甲", 0.0, 0.0, 2.0, 4.0)]


@pytest.mark.parametrize("escape", ["Unknown(_ENV)", "local E=_ENV;Unknown(E)"])
def test_standard_environment_escape_keeps_global_handle_effects(escape: str) -> None:
    source = f"local q=Location(3,4);p=Location(1,2);{escape};CreateItemLoc(FourCC('I001'),p);CreateItemLoc(FourCC('I002'),q)"
    analysis = analyze_script_placements(source, lua=True)
    assert [row.row() for row in analysis.placements] == [("I002", 3.0, 4.0, "item")]
    assert (
        len(analysis.diagnostics) == 1 and "几何句柄" in analysis.diagnostics[0].reason
    )


@pytest.mark.parametrize(
    "write",
    [
        "function Change()_ENV={}end",
        "if Runtime()then _ENV={}end",
        "local E;E=E;local _ENV=E",
    ],
)
def test_environment_replacements_with_unproved_order_stay_diagnostic(
    write: str,
) -> None:
    source = f"{write};CreateItem(FourCC('I001'),1,2)"
    analysis = analyze_script_placements(source, lua=True)
    assert not analysis.placements and "_ENV" in analysis.diagnostics[0].reason


def test_jass_variable_named_environment_has_no_lua_role() -> None:
    source = "function S takes nothing returns nothing\nlocal integer _ENV=0\ncall CreateItem('I001',1,2)\nendfunction"
    assert script_placements(source, lua=False) == [("I001", 1.0, 2.0, "item")]


def test_changed_captured_environment_does_not_reuse_old_private_fields() -> None:
    source = "local Make=Rect;local _ENV={};function Rect(a,b,c,d)return Make(a,b,c,d)end;function F()gg_rct_A=Rect(0,0,2,4)end;_ENV={}"
    result = analyze_script_rectangles(source, lua=True)
    assert not result.rectangles and "_ENV" in result.diagnostics[0].reason


def test_saved_historical_function_aliases_are_not_mistaken_for_cycles() -> None:
    source = "local Make=Rect;local Saved=Make;Make=Saved;gg_rct_A=Make(0,0,2,4);gg_rct_B=Saved(10,20,30,40)"
    assert script_rectangles(source, lua=True) == [
        ("gg_rct_A", 0.0, 0.0, 2.0, 4.0),
        ("gg_rct_B", 10.0, 20.0, 30.0, 40.0),
    ]


def test_alias_resolution_work_grows_linearly_with_shared_prefixes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    original = ScriptFunctionBindings._write

    def counted(self, symbol, owner, position):
        nonlocal calls
        calls += 1
        return original(self, symbol, owner, position)

    monkeypatch.setattr(ScriptFunctionBindings, "_write", counted)
    sizes = []
    for count in [300, 600]:
        calls = 0
        source = (
            "local A0=Rect;"
            + ";".join(f"local A{i}=A{i - 1}" for i in range(1, count + 1))
            + f";gg_rct_Perf=A{count}(0,0,2,4)"
        )
        assert script_rectangles(source, lua=True) == [
            ("gg_rct_Perf", 0.0, 0.0, 2.0, 4.0)
        ]
        sizes.append(calls)
    assert sizes[0] > 0 and sizes[1] < sizes[0] * 3


def test_2500_aliases_do_not_use_python_recursion_or_a_depth_quota() -> None:
    source = (
        "local G0=_G;"
        + ";".join(f"local G{i}=G{i - 1}" for i in range(1, 2501))
        + ";local _ENV=G2500;gg_rct_A=Rect(0,0,2,4)"
    )
    assert script_rectangles(source, lua=True) == [("gg_rct_A", 0.0, 0.0, 2.0, 4.0)]


def test_many_environment_writes_are_indexed_once_and_keep_every_diagnostic() -> None:
    count = 600
    source = ";".join(
        f"_ENV={{}};CreateItem(FourCC('I001'),{i},2)" for i in range(count)
    )
    analysis = analyze_script_placements(source, lua=True)
    assert not analysis.placements and len(analysis.diagnostics) == count
    assert str(count - 1) in analysis.diagnostics[-1].expression
    functions = script_functions(source, lua=True)
    assert functions.symbols.environments is not None
    assert len(functions.symbols.environments.offsets[(None, -1, "_ENV")]) == count


def test_near_campaign_and_guide_share_environment_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")
    good = "local _ENV=_G;_ENV.CreateItem(_ENV.FourCC('I001'),1,2);_ENV.gg_rct_A=_ENV.Rect(0,0,2,4)"
    bad = "local _ENV={};CreateItem(FourCC('I002'),1,2);gg_rct_B=Rect(0,0,2,4)"
    for name, source in [("001", good), ("002", bad)]:
        scripts = tmp_path / "子地图" / name / "脚本可读文本"
        scripts.mkdir(parents=True)
        (scripts / "war3map.lua").write_text(source, encoding="utf-8")
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "near", "1 2 0", limit=1)
    )
    data = json.loads(result.render(as_json=True))
    assert result.exit_code == 0 and data["has_matches"]
    assert len(data["entries"]) == len(data["regions"]) == 1
    assert data["entries"][0]["code"] == "I001"
    assert len(data["spatial_diagnostics"]) == 2
    assert all(
        row["section"] == "子地图 002" and "_ENV" in row["message"]
        for row in data["spatial_diagnostics"]
    )
    assert script_position_groups(
        MapData(
            path="synthetic.w3x", name="environment", scripts={"war3map.lua": good}
        ),
        "item",
    ) == {"I001": ((1.0, 2.0),)}
    assert not script_position_groups(
        MapData(path="synthetic.w3x", name="environment", scripts={"war3map.lua": bad}),
        "item",
    )


@pytest.mark.parametrize("binding", ["local _ENV=_G", "local _ENV={}"])
def test_original_environment_call_is_not_reinterpreted_as_independent_legacy_index(
    binding: str,
) -> None:
    expression = "_ENV.CreateItem(_ENV.FourCC('I001'),1,2)"
    source = binding + ";" + expression
    context = AnalysisScriptSource("war3map.lua", source, True)
    result = indexed_placements(
        (context,), ((("war3map.lua", "1"), expression, str(len(binding) + 1)),)
    )
    assert not result.placements and not result.diagnostics
