"""Global environment fields, ordinary globals, private tables and readonly aliases."""

import json
from pathlib import Path

import pytest

from gametool import pack_query_cli as queries
from gametool.map_data import MapData
from gametool.pack_query_options import PackQueryCliOptions
from gametool.pack_query_placements import script_placements, script_rectangles
from gametool.placement_positions import script_position_groups
from gametool.script_function_graph import script_functions
from gametool.script_geometry import GeometryAliases
from gametool.script_placement_analysis import analyze_script_placements


@pytest.mark.parametrize(
    "first,second", [("gg_rct_A", "gg_rct_B"), ("gg_rct_甲", "gg_rct_乙")]
)
@pytest.mark.parametrize("write_prefix", ["", "_G . "])
@pytest.mark.parametrize("read_prefix", ["", "_G . "])
def test_independent_global_regions_do_not_share_environment_aliases(
    first: str, second: str, write_prefix: str, read_prefix: str
) -> None:
    source = f"{write_prefix}{first}=Rect(0,0,2,4);{write_prefix}{second}=Rect(10,20,30,40);RemoveRect({read_prefix}{second});CreateItemLoc(FourCC('I001'),GetRectCenter({read_prefix}{first}))"
    assert script_placements(source, lua=True) == [("I001", 1.0, 2.0, "item")]
    assert script_rectangles(source, lua=True) == [(first, 0.0, 0.0, 2.0, 4.0)]


@pytest.mark.parametrize(
    "alias", ["_G.gg_rct_B=gg_rct_A", "gg_rct_B=_G.gg_rct_A", "_G.gg_rct_B=_G.gg_rct_A"]
)
def test_real_aliases_across_global_spellings_keep_mutation_evidence(
    alias: str,
) -> None:
    source = f"gg_rct_A=Rect(0,0,2,4);{alias};RemoveRect(gg_rct_B);CreateItemLoc(FourCC('I001'),GetRectCenter(_G.gg_rct_A))"
    analysis = analyze_script_placements(source, lua=True)
    assert not analysis.placements and "几何句柄" in analysis.diagnostics[0].reason


def test_explicit_global_region_bypasses_same_named_local_variable() -> None:
    source = "_G.gg_rct_A=Rect(0,0,2,4);local gg_rct_A=Rect(10,20,30,40);CreateItemLoc(FourCC('I001'),GetRectCenter(_G.gg_rct_A));CreateItemLoc(FourCC('I002'),GetRectCenter(gg_rct_A))"
    assert script_placements(source, lua=True) == [
        ("I001", 1.0, 2.0, "item"),
        ("I002", 20.0, 30.0, "item"),
    ]


@pytest.mark.parametrize("binding", ["local _G={}", "_G={}", "_G._G={}"])
def test_private_or_replaced_global_table_never_overwrites_ordinary_global(
    binding: str,
) -> None:
    source = f"p=Location(1,2);{binding};_G.p=Location(3,4);CreateItemLoc(FourCC('I001'),p);CreateItemLoc(FourCC('I002'),_G.p)"
    assert script_placements(source, lua=True) == [
        ("I001", 1.0, 2.0, "item"),
        ("I002", 3.0, 4.0, "item"),
    ]


def test_function_parameter_named_global_environment_is_a_private_receiver() -> None:
    source = "p=Location(1,2);function S(_G,q)_G.p=q;CreateItemLoc(FourCC('I002'),_G.p)end S({},Location(3,4));CreateItemLoc(FourCC('I001'),p)"
    assert {row[:3] for row in script_placements(source, lua=True)} == {
        ("I001", 1.0, 2.0),
        ("I002", 3.0, 4.0),
    }


@pytest.mark.parametrize("shadow", ["local _G={}", "_G={}"])
def test_captured_environment_native_keeps_its_original_binding(shadow: str) -> None:
    source = (
        f"local Make=_G.Location;{shadow};CreateItemLoc(FourCC('I001'),Make(1.25,-2.5))"
    )
    assert script_placements(source, lua=True) == [("I001", 1.25, -2.5, "item")]


def test_replaced_environment_member_function_is_followed_as_source() -> None:
    source = "_G={};function _G.OffsetLocation(p,x,y)return p end CreateItemLoc(FourCC('I001'),_G.OffsetLocation(Location(1,2),3,4))"
    assert script_placements(source, lua=True) == [("I001", 1.0, 2.0, "item")]


@pytest.mark.parametrize(
    "exposure",
    [
        "Unknown(_G)",
        "local E=_G;Unknown(E)",
        "function Escape(E)Unknown(E)end Escape(_G)",
        "function Mutate(E)RemoveLocation(E.p)end Mutate(_G)",
    ],
)
def test_environment_escape_still_diagnoses_all_accessible_global_handles(
    exposure: str,
) -> None:
    source = f"p=Location(1,2);q=Location(3,4);{exposure};CreateItemLoc(FourCC('I001'),p);CreateItemLoc(FourCC('I002'),q)"
    analysis = analyze_script_placements(source, lua=True)
    assert not analysis.placements and len(analysis.diagnostics) == 2
    assert all("几何句柄" in row.reason for row in analysis.diagnostics)


def test_environment_escape_does_not_reach_unexposed_local_geometry() -> None:
    source = "local p=Location(1,2);q=Location(3,4);Unknown(_G);CreateItemLoc(FourCC('I001'),p);CreateItemLoc(FourCC('I002'),q)"
    analysis = analyze_script_placements(source, lua=True)
    assert [row.row() for row in analysis.placements] == [("I001", 1.0, 2.0, "item")]
    assert (
        len(analysis.diagnostics) == 1 and "I002" in analysis.diagnostics[0].expression
    )


@pytest.mark.parametrize(
    "binding", ["p=Location(1,2);local q=p", "local q=Location(1,2);p=q"]
)
def test_environment_escape_follows_real_global_local_handle_aliases(
    binding: str,
) -> None:
    source = f"{binding};Unknown(_G);CreateItemLoc(FourCC('I001'),q)"
    assert not script_placements(source, lua=True)


@pytest.mark.parametrize(
    "predicate,args",
    [
        ("RectContainsCoords", "r,0,0"),
        ("RectContainsLoc", "r,p"),
        ("RectContainsUnit", "r,RuntimeUnit()"),
        ("RectContainsItem", "RuntimeItem(),r"),
    ],
)
@pytest.mark.parametrize(
    "binding,call",
    [
        ("local Check=NAME", "Check"),
        ("Check=_G.NAME", "Check"),
        ("local T={};T.Check=NAME", "T . Check"),
    ],
)
def test_readonly_predicate_aliases_preserve_both_input_handles(
    predicate: str, args: str, binding: str, call: str
) -> None:
    source = f"local r=Rect(0,0,2,4);local p=Location(1,2);{binding.replace('NAME', predicate)};{call}({args});CreateItemLoc(FourCC('I001'),p);gg_rct_Test=r"
    assert script_placements(source, lua=True) == [("I001", 1.0, 2.0, "item")]
    assert script_rectangles(source, lua=True) == [("gg_rct_Test", 0.0, 0.0, 2.0, 4.0)]


@pytest.mark.parametrize(
    "predicate,args",
    [
        ("RectContainsCoords", "r,0,0"),
        ("RectContainsLoc", "r,p"),
        ("RectContainsUnit", "r,RuntimeUnit()"),
        ("RectContainsItem", "RuntimeItem(),r"),
    ],
)
def test_readonly_result_does_not_alias_predicate_geometry_inputs(
    predicate: str, args: str
) -> None:
    source = f"local r=Rect(0,0,2,4);local p=Location(1,2);local Check={predicate};local flag=Check({args});Unknown(flag);CreateItemLoc(FourCC('I001'),p);gg_rct_Test=r"
    assert script_placements(source, lua=True) == [("I001", 1.0, 2.0, "item")]
    assert script_rectangles(source, lua=True) == [("gg_rct_Test", 0.0, 0.0, 2.0, 4.0)]


def test_capture_before_readonly_global_redefinition_keeps_standard_function() -> None:
    source = "local Check=RectContainsLoc;RectContainsLoc=function(r,p)RemoveLocation(p)end local r=Rect(0,0,2,4);local p=Location(1,2);Check(r,p);CreateItemLoc(FourCC('I001'),p)"
    assert script_placements(source, lua=True) == [("I001", 1.0, 2.0, "item")]


def test_capture_after_readonly_redefinition_traces_actual_mutation() -> None:
    source = "RectContainsLoc=function(r,p)RemoveLocation(p)end local Check=RectContainsLoc;local r=Rect(0,0,2,4);local p=Location(1,2);Check(r,p);CreateItemLoc(FourCC('I001'),p)"
    assert not script_placements(source, lua=True)


def test_predicate_result_is_never_promoted_to_location() -> None:
    source = "local r=Rect(0,0,2,4);local Check=RectContainsLoc;CreateItemLoc(FourCC('I001'),Check(r,Location(1,2)))"
    analysis = analyze_script_placements(source, lua=True)
    assert not analysis.placements and "只读区域判断" in analysis.diagnostics[0].reason


def test_3000_environment_fields_and_escape_sites_keep_all_effects() -> None:
    count = 3000
    source = (
        ";".join(f"_G.p{i}=Location({i},0)" for i in range(count))
        + ";"
        + ";".join("Unknown(_G)" for _ in range(count))
    )
    functions = script_functions(source, lua=True)
    aliases = GeometryAliases(functions)
    assert len(aliases.mutations("p0", None, len(source))) == count
    assert len(aliases.mutations(f"_G.p{count - 1}", None, len(source))) == count


def test_1500_unaffected_global_regions_survive_one_other_region_mutation() -> None:
    count = 1500
    source = (
        ";".join(f"_G.gg_rct_R{i}=Rect({i},0,{i + 1},2)" for i in range(count))
        + ";RemoveRect(_G.gg_rct_R0)"
    )
    rows = script_rectangles(source, lua=True)
    assert len(rows) == count - 1 and rows[-1] == (
        f"gg_rct_R{count - 1}",
        float(count - 1),
        0.0,
        float(count),
        2.0,
    )


def test_near_and_guide_preserve_global_wrapped_region_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")
    source = "_G.gg_rct_甲=Rect(0,0,2,4);_G.gg_rct_乙=Rect(10,20,30,40);RemoveRect(_G.gg_rct_乙);CreateUnitAtLoc(Player(0),FourCC('n001'),GetRectCenter(_G.gg_rct_甲),0)"
    scripts = tmp_path / "脚本可读文本"
    scripts.mkdir()
    (scripts / "war3map.lua").write_text(source, encoding="utf-8")
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "near", "1 2 0")
    )
    row = json.loads(result.render(as_json=True))["entries"][0]
    assert (row["code"], row["x"], row["y"], row["dist"]) == (
        "n001",
        1.0,
        2.0,
        0.0,
    ) and "所在矩形: gg_rct_甲" in result.render()
    assert script_position_groups(
        MapData(path="synthetic.w3x", name="全局身份", scripts={"war3map.lua": source})
    ) == {"n001": ((1.0, 2.0),)}
