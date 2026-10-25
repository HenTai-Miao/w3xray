"""Complete source arithmetic feeds geometry without executing source code."""

import json
from pathlib import Path

import pytest

from gametool import pack_query_cli as queries
from gametool.map_data import MapData
from gametool.pack_query_options import PackQueryCliOptions
from gametool.pack_query_placements import script_placements, script_rectangles
from gametool.placement_positions import script_position_groups
from gametool.script_function_graph import script_functions
from gametool.script_numeric_expressions import numeric_expression
from gametool.script_placement_analysis import analyze_script_placements
from gametool.script_rectangle_analysis import analyze_script_rectangles


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("x+1", 3),
        ("-x", -2),
        ("-x^2", -4),
        ("x^-2", 0.25),
        ("x^3^2", 512),
        ("(x+1)*y", 12),
        ("y/(x-1)", 4),
        ("y//(x+1)", 1),
        ("-y%3", 2),
        ("x+1e-3", 2.001),
        ("x+0x10+$20", 50),
        ("x --[[ opaque +999 ]] +1", 3),
    ],
)
def test_numeric_precedence_variables_and_comments(
    expression: str, expected: float
) -> None:
    source = f"function P(x,y) return Location({expression},y*2) end CreateItemLoc(FourCC('I001'),P(2,4))"
    assert script_placements(source, lua=True) == [("I001", expected, 8.0, "item")]


@pytest.mark.parametrize(
    "source",
    [
        "function X(x)return x+1 end CreateItemLoc(FourCC('I001'),Location(X(2),4*2))",
        "local x=1+2;local y=x*2+2;CreateItemLoc(FourCC('I001'),Location(x,y))",
        "local x,y=1+2,4*2;CreateItemLoc(FourCC('I001'),Location(x,y))",
        "function Pair(a,b)return a+1,b*2 end local x,y=Pair(2,4);CreateItemLoc(FourCC('I001'),Location(x,y))",
        "function Pair(a,b)return a+1,b*2 end CreateItemLoc(FourCC('I001'),Location(Pair(2,4)))",
        "function Pair(a,b)return a+1,b*2 end CreateItem(FourCC('I001'),Pair(2,4))",
        "local T={};T.x=1+2;T.y=4*2;CreateItemLoc(FourCC('I001'),Location(T.x,T.y))",
        "local T={};function T:X(x)return x+1 end CreateItemLoc(FourCC('I001'),Location(T:X(2),4*2))",
        "local p=Location(1,2);CreateItemLoc(FourCC('I001'),Location(GetLocationX(p)+2,GetLocationY(p)*4))",
        "local r=Rect(0,0,4,12);CreateItemLoc(FourCC('I001'),Location(GetRectCenterX(r)+1,GetRectCenterY(r)+2))",
        "local x,y=2,4;x,y=x+1,y*2;CreateItemLoc(FourCC('I001'),Location(x,y))",
        "local x=2;do local x=x+1;CreateItemLoc(FourCC('I001'),Location(x,4*2)) end",
    ],
)
def test_arithmetic_getters_assignments_and_multi_values(source: str) -> None:
    assert script_placements(source, lua=True) == [("I001", 3.0, 8.0, "item")]


@pytest.mark.parametrize("lua", [True, False])
def test_language_specific_numeric_contexts_reach_rectangles(lua: bool) -> None:
    source = (
        "function R(x,y)return Rect(x-1,y-2,x+1,y+2)end gg_rct_Test=R(3,8)"
        if lua
        else "function R takes real x, real y returns rect\nreturn Rect(x-1,y-2,x+1,y+2)\nendfunction\nset gg_rct_Test=R(3,8)"
    )
    assert script_rectangles(source, lua=lua) == [("gg_rct_Test", 2.0, 6.0, 4.0, 10.0)]


@pytest.mark.parametrize(
    "expression",
    [
        "Runtime()+1",
        "'3'+1",
        '"3"+1',
        "true+1",
        "nil+1",
        "FourCC('I001')+1",
        "Location(1,2)+1",
        "1/0",
        "(-1)^0.5",
        "1e308*1e308",
        "x/(x-x)",
        "x and 1",
        "x or 1",
        "x+1..'2'",
        "x+1&3",
        "x+1<3",
        "x+1[2]",
        "x+",
        "(x+1",
        "x+1)",
        "__import__('os').system('noop')+1",
    ],
)
def test_unknown_or_unsupported_arithmetic_remains_diagnostic(expression: str) -> None:
    source = f"function P(x)return Location({expression},0)end CreateItemLoc(FourCC('I001'),P(2))"
    analysis = analyze_script_placements(source, lua=True)
    assert not analysis.placements and analysis.diagnostics


def test_assignment_suffix_is_not_silently_discarded() -> None:
    for suffix in (
        "and 8",
        "or 8",
        "..'8'",
        "&8",
        "<8",
        ".y",
        "[1]",
        "==3",
        "!=3",
        "(8)",
        ")",
    ):
        source = f"local x=1+2 {suffix};CreateItemLoc(FourCC('I001'),Location(x,0))"
        assert not script_placements(source, lua=True), suffix


@pytest.mark.parametrize("expression", ["1==1", "1!=1", "1(2)", "1+2^3", "1+2==3"])
def test_jass_unsupported_assignment_suffixes_are_not_numeric(expression: str) -> None:
    source = f"function S takes nothing returns nothing\nlocal real x={expression}\ncall CreateItemLoc('I001',Location(x,0))\nendfunction"
    assert not script_placements(source, lua=False)


def test_arithmetic_alias_does_not_alias_numeric_results_to_geometry_handles() -> None:
    source = "local p=Location(1,2);local x=GetLocationX(p)+1;Unknown(x);CreateItemLoc(FourCC('I001'),p)"
    assert script_placements(source, lua=True) == [("I001", 1.0, 2.0, "item")]


@pytest.mark.parametrize(
    "effect", ["MoveLocation(p,8,9)", "RemoveLocation(p)", "Unknown(p)"]
)
def test_geometry_effects_still_reject_arithmetic_getters(effect: str) -> None:
    source = f"local p=Location(1,2);{effect};CreateItemLoc(FourCC('I001'),Location(GetLocationX(p)+1,GetLocationY(p)*2))"
    analysis = analyze_script_placements(source, lua=True)
    assert not analysis.placements and "几何句柄" in analysis.diagnostics[0].reason


@pytest.mark.parametrize(
    "functions",
    [
        "function F(x) CreateItem(FourCC('I001'),x,0);F(x+1) end F(1)",
        "function F(x) CreateItem(FourCC('I001'),x,0);G(x+1) end function G(x)F(x+1)end F(1)",
        "function F(p) CreateItemLoc(FourCC('I001'),p);F(Location(GetLocationX(p)+1,0))end F(Location(1,0))",
    ],
)
def test_changing_recursive_contexts_stay_symbolic_with_visible_diagnostics(
    functions: str,
) -> None:
    analysis = analyze_script_placements(functions, lua=True)
    assert any(row.row() == ("I001", 1.0, 0.0, "item") for row in analysis.placements)
    assert any("递归数值或几何变换" in row.reason for row in analysis.diagnostics)
    assert len(script_functions(functions, lua=True).source_graph().nodes) < 20


def test_recursive_arithmetic_return_finishes_without_a_numeric_budget() -> None:
    source = (
        "function F(x)return F(x+1)end CreateItemLoc(FourCC('I001'),Location(F(1),0))"
    )
    analysis = analyze_script_placements(source, lua=True)
    assert not analysis.placements and "递归环" in analysis.diagnostics[0].reason


def test_constant_arithmetic_recursion_retains_encoded_finite_contexts() -> None:
    source = "function F(x) CreateItem(FourCC('I001'),x,0);F(1+1)end F(1)"
    assert {row[:3] for row in script_placements(source, lua=True)} == {
        ("I001", 1.0, 0.0),
        ("I001", 2.0, 0.0),
    }


def test_same_numeric_dependency_in_many_occurrences_is_not_truncated() -> None:
    count = 12000
    source = (
        "function P(x)return Location("
        + "+".join(["x"] * count)
        + ",0)end CreateItemLoc(FourCC('I001'),P(1.25))"
    )
    assert script_placements(source, lua=True) == [("I001", count * 1.25, 0.0, "item")]


def test_deep_numeric_getters_use_the_existing_iterative_evaluator() -> None:
    depth = 1050
    source = (
        "\n".join(f"function F{i}(x)return F{i + 1}(x)+1 end" for i in range(depth))
        + f"\nfunction F{depth}(x)return x end CreateItemLoc(FourCC('I001'),Location(F0(1.25),0))"
    )
    assert script_placements(source, lua=True) == [("I001", depth + 1.25, 0.0, "item")]


def test_1500_transformed_contexts_keep_every_point_and_rectangle() -> None:
    n = 1500
    source = (
        "function S(x,y) local p=Location(x+1,y*2);CreateItemLoc(FourCC('I001'),p);gg_rct_Test=Rect(x-1,y-1,x+1,y+1)end\n"
        + "\n".join(f"S({i}.25,-{i}.5)" for i in range(n))
    )
    assert (
        len(script_placements(source, lua=True))
        == len(script_rectangles(source, lua=True))
        == n
    )
    assert not analyze_script_rectangles(source, lua=True).diagnostics


def test_numeric_plan_substitutes_only_full_scalar_operands() -> None:
    plan = numeric_expression("X('a+b') + T . x * 1e-3", lua=True)
    assert plan is not None
    assert [part.expression for part in plan.operands] == ["X('a+b')", "T . x"]
    assert plan.render(("-2", "4")) == "(-2) + (4) * 1e-3"


def test_near_json_regions_and_guide_share_arithmetic_positions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")
    source = "function S(x,y)CreateUnitAtLoc(Player(0),FourCC('n001'),Location(x+0.25,y*2),0);gg_rct_区域=Rect(x-1,y-1,x+1,y+1)end S(10,-2)"
    scripts = tmp_path / "脚本可读文本"
    scripts.mkdir()
    (scripts / "war3map.lua").write_text(source, encoding="utf-8")
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "near", "10.25 -4 0")
    )
    row = json.loads(result.render(as_json=True))["entries"][0]
    assert (row["code"], row["x"], row["y"], row["dist"]) == (
        "n001",
        10.25,
        -4.0,
        0.0,
    ) and row["positions"] == [[10.25, -4.0]]
    assert script_position_groups(
        MapData(path="synthetic.w3x", name="数值", scripts={"war3map.lua": source})
    ) == {"n001": ((10.25, -4.0),)}
