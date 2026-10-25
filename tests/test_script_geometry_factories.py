"""Standard fresh geometry factories retain complete, source-backed evidence."""

import json
from pathlib import Path

import pytest

from gametool import pack_query_cli as queries
from gametool.map_data import MapData
from gametool.pack_query_options import PackQueryCliOptions
from gametool.pack_query_placements import script_placements, script_rectangles
from gametool.placement_positions import script_position_groups
from gametool.script_function_graph import script_functions
from gametool.script_names import rectangle_name
from gametool.script_placement_analysis import analyze_script_placements
from gametool.script_rectangle_analysis import analyze_script_rectangles


@pytest.mark.parametrize(
    ("expression", "bounds"),
    [
        (
            "RectFromLoc(Location(-10.25,-20.5),Location(30.75,40.125))",
            (-10.25, -20.5, 30.75, 40.125),
        ),
        (
            "OffsetRectBJ(Rect(-10.25,-20.5,30.75,40.125),2,3)",
            (-8.25, -17.5, 32.75, 43.125),
        ),
        ("RectFromCenterSizeBJ(Location(1.25,-2.5),4,8)", (-0.75, -6.5, 3.25, 1.5)),
        (
            "OffsetRectBJ(RectFromLoc(Location(-10,-20),Location(30,40)),1+1,6/2)",
            (-8, -17, 32, 43),
        ),
        (
            "OffsetRectBJ(RectFromCenterSizeBJ(Location(1.25,-2.5),4,8),2,3)",
            (1.25, -3.5, 5.25, 4.5),
        ),
    ],
)
@pytest.mark.parametrize("lua", [True, False])
def test_standard_rect_factories_in_both_languages(
    expression: str, bounds: tuple[float, ...], lua: bool
) -> None:
    source = ("" if lua else "set ") + f"gg_rct_Test={expression}"
    assert script_rectangles(source, lua=lua) == [("gg_rct_Test", *bounds)]
    assert not analyze_script_rectangles(source, lua=lua).diagnostics


@pytest.mark.parametrize(
    "expression",
    [
        "OffsetLocation(Location(1.25,-2.5),3,4)",
        "OffsetLocation(OffsetLocation(Location(1.25,-2.5),1,1),2,3)",
        "GetRectCenter(OffsetRectBJ(Rect(0,-2,2,0),3.25,2.5))",
        "GetRectCenter(RectFromCenterSizeBJ(Location(4.25,1.5),8,4))",
        "GetRectCenter(RectFromLoc(Location(0,0),Location(8.5,3)))",
    ],
)
def test_derived_locations_and_rect_centers_reach_native_positions(
    expression: str,
) -> None:
    assert script_placements(
        f"CreateItemLoc(FourCC('I001'),{expression})", lua=True
    ) == [("I001", 4.25, 1.5, "item")]


def test_getters_aliases_methods_and_parameters_share_factory_values() -> None:
    source = "local T={};function T:P(x,y)return OffsetLocation(Location(x,y),3,4)end function T:R(p)return RectFromCenterSizeBJ(p,8,4)end function S(p,r)CreateItemLoc(FourCC('I001'),p);gg_rct_Test=r end local P=T.P;local p=P(T,1.25,-2.5);S(p,T:R(p))"
    assert script_placements(source, lua=True) == [("I001", 4.25, 1.5, "item")]
    assert script_rectangles(source, lua=True) == [
        ("gg_rct_Test", 0.25, -0.5, 8.25, 3.5)
    ]


def test_lua_multireturn_and_varargs_supply_all_geometry_inputs() -> None:
    source = "function Points()return Location(-10,-20),Location(30,40)end function S(...)gg_rct_Test=RectFromLoc(...)end S(Points())"
    assert script_rectangles(source, lua=True) == [
        ("gg_rct_Test", -10.0, -20.0, 30.0, 40.0)
    ]


@pytest.mark.parametrize(
    "expression",
    [
        "RectFromLoc(Location(1,2),RuntimeLocation())",
        "RectFromLoc(Location(1,2))",
        "RectFromLoc('Location(1,2)',Location(3,4))",
        "RectFromLoc(Rect(1,2,3,4),Location(3,4))",
        "OffsetRectBJ(Rect(0,0,1,1),Runtime(),0)",
        "OffsetRectBJ(Rect(0,0,1,1),'3',0)",
        "OffsetRectBJ(Rect(0,0,1,1),1e308*1e308,0)",
        "OffsetRectBJ(Rect(1e308,0,1e308,1),1e308,0)",
        "RectFromCenterSizeBJ(Location(0,0),Runtime(),4)",
        "RectFromCenterSizeBJ(Location(0,0),4)",
        "RectFromCenterSizeBJ(Location(1e308,0),1e308*2,4)",
        "CopyRect(Rect(0,0,1,1))",
        "OffsetRect(Rect(0,0,1,1),0,0)",
    ],
)
def test_unknown_wrong_typed_missing_nonfinite_or_nonstandard_rect_factories_remain_diagnostic(
    expression: str,
) -> None:
    analysis = analyze_script_rectangles(f"gg_rct_Test={expression}", lua=True)
    assert not analysis.rectangles and len(analysis.diagnostics) == 1
    assert expression in analysis.diagnostics[0].expression


@pytest.mark.parametrize(
    "expression",
    [
        "OffsetLocation(Location(0,0),Runtime(),0)",
        "OffsetLocation(Location(1e308,0),1e308,0)",
        "OffsetLocation(Location(1,2),3)",
        "OffsetLocation('Location(1,2)',3,4)",
    ],
)
def test_unknown_or_nonfinite_location_offsets_are_not_points(expression: str) -> None:
    analysis = analyze_script_placements(
        f"CreateItemLoc(FourCC('I001'),{expression})", lua=True
    )
    assert not analysis.placements and analysis.diagnostics


@pytest.mark.parametrize(
    "effect", ["MoveLocation(p,8,9)", "RemoveLocation(p)", "Unknown(p)"]
)
@pytest.mark.parametrize(
    "factory", ["RectFromLoc(p,Location(3,4))", "RectFromCenterSizeBJ(p,4,8)"]
)
def test_location_input_effects_block_dependent_rectangles(
    effect: str, factory: str
) -> None:
    analysis = analyze_script_rectangles(
        f"local p=Location(1,2);{effect};gg_rct_Test={factory}", lua=True
    )
    assert not analysis.rectangles and "几何句柄" in analysis.diagnostics[0].reason


@pytest.mark.parametrize(
    "effect", ["SetRect(r,0,0,1,1)", "RemoveRect(r)", "Unknown(r)"]
)
def test_rect_input_effects_block_offset_coordinates(effect: str) -> None:
    source = f"local r=Rect(0,0,2,4);{effect};CreateItemLoc(FourCC('I001'),GetRectCenter(OffsetRectBJ(r,1,2)))"
    analysis = analyze_script_placements(source, lua=True)
    assert not analysis.placements and "几何句柄" in analysis.diagnostics[0].reason


@pytest.mark.parametrize(
    "effect", ["RemoveLocation(q)", "MoveLocation(q,8,9)", "Unknown(q)"]
)
def test_fresh_offset_output_does_not_alias_the_original_location(effect: str) -> None:
    source = f"local p=Location(1.25,-2.5);local q=OffsetLocation(p,3,4);{effect};CreateItemLoc(FourCC('I001'),p)"
    assert script_placements(source, lua=True) == [("I001", 1.25, -2.5, "item")]


@pytest.mark.parametrize(
    "effect", ["RemoveRect(q)", "SetRect(q,8,9,10,11)", "Unknown(q)"]
)
def test_fresh_offset_rect_does_not_alias_original_rectangle(effect: str) -> None:
    source = f"local r=Rect(-10,-20,30,40);local q=OffsetRectBJ(r,0,0);{effect};gg_rct_Test=r"
    assert script_rectangles(source, lua=True) == [
        ("gg_rct_Test", -10.0, -20.0, 30.0, 40.0)
    ]


def test_rect_from_locations_output_mutation_does_not_mutate_inputs() -> None:
    source = "local p=Location(1,2);local q=Location(3,4);local r=RectFromLoc(p,q);RemoveRect(r);CreateItemLoc(FourCC('I001'),p);CreateItemLoc(FourCC('I002'),q)"
    assert script_placements(source, lua=True) == [
        ("I001", 1.0, 2.0, "item"),
        ("I002", 3.0, 4.0, "item"),
    ]


def test_source_override_returning_original_handle_preserves_alias_effects() -> None:
    source = "function OffsetLocation(p,x,y)return p end local p=Location(1,2);local q=OffsetLocation(p,3,4);RemoveLocation(q);CreateItemLoc(FourCC('I001'),p)"
    assert not script_placements(source, lua=True)


def test_captured_standard_factory_alias_survives_later_global_replacement() -> None:
    source = "local Offset=OffsetLocation;OffsetLocation=Runtime;CreateItemLoc(FourCC('I001'),Offset(Location(1.25,-2.5),3,4))"
    assert script_placements(source, lua=True) == [("I001", 4.25, 1.5, "item")]


@pytest.mark.parametrize(
    "factory", ["RectFromLoc", "OffsetLocation", "OffsetRectBJ", "RectFromCenterSizeBJ"]
)
def test_shadowed_global_factory_never_uses_standard_semantics(factory: str) -> None:
    args = {
        "RectFromLoc": "Location(0,0),Location(2,4)",
        "OffsetLocation": "Location(1,2),3,4",
        "OffsetRectBJ": "Rect(0,0,2,4),1,2",
        "RectFromCenterSizeBJ": "Location(1,2),3,4",
    }[factory]
    source = f"local _G={{}};gg_rct_Test=_G.{factory}({args});CreateItemLoc(FourCC('I001'),_G.{factory}({args}))"
    assert not script_rectangles(source, lua=True) and not script_placements(
        source, lua=True
    )


@pytest.mark.parametrize(
    "predicate",
    [
        "RectContainsCoords(r,0,0)",
        "RectContainsLoc(r,p)",
        "RectContainsUnit(r,RuntimeUnit())",
        "RectContainsItem(RuntimeItem(),r)",
    ],
)
def test_standard_readonly_predicates_do_not_invalidate_input_geometry(
    predicate: str,
) -> None:
    source = f"local r=Rect(-10,-20,30,40);local p=Location(1,2);{predicate};gg_rct_Test=r;CreateItemLoc(FourCC('I001'),p)"
    assert script_rectangles(source, lua=True) == [
        ("gg_rct_Test", -10.0, -20.0, 30.0, 40.0)
    ]
    assert script_placements(source, lua=True) == [("I001", 1.0, 2.0, "item")]


def test_shadowed_readonly_predicate_mutations_are_still_traced() -> None:
    source = "function RectContainsCoords(r,x,y)RemoveRect(r)end local r=Rect(0,0,2,4);RectContainsCoords(r,0,0);gg_rct_Test=r"
    assert not script_rectangles(source, lua=True)


def test_recursive_offset_geometry_stays_symbolic_without_expansion_budget() -> None:
    source = "function F(p)CreateItemLoc(FourCC('I001'),p);F(OffsetLocation(p,1,0))end F(Location(1,2))"
    analysis = analyze_script_placements(source, lua=True)
    assert [row.row() for row in analysis.placements] == [("I001", 1.0, 2.0, "item")]
    assert any("递归数值或几何变换" in row.reason for row in analysis.diagnostics)
    assert len(script_functions(source, lua=True).source_graph().nodes) < 10


def test_1500_derived_positions_and_rectangles_are_not_capped() -> None:
    count = 1500
    source = (
        "function S(x,y)local p=OffsetLocation(Location(x,y),.25,-.5);CreateItemLoc(FourCC('I001'),p);gg_rct_Test=OffsetRectBJ(RectFromCenterSizeBJ(p,4,8),1,2)end\n"
        + "\n".join(f"S({i},-{i})" for i in range(count))
    )
    assert (
        len(script_placements(source, lua=True))
        == len(script_rectangles(source, lua=True))
        == count
    )
    assert (
        not analyze_script_placements(source, lua=True).diagnostics
        and not analyze_script_rectangles(source, lua=True).diagnostics
    )


def test_1050_geometry_factory_forwarding_levels_are_iterative() -> None:
    depth = 1050
    source = (
        "\n".join(f"function F{i}(p)return F{i + 1}(p)end" for i in range(depth))
        + f"\nfunction F{depth}(p)return OffsetLocation(p,3,4)end CreateItemLoc(FourCC('I001'),F0(Location(1.25,-2.5)))"
    )
    assert script_placements(source, lua=True) == [("I001", 4.25, 1.5, "item")]


def test_near_and_guide_share_standard_factory_positions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")
    source = "gg_rct_区域=OffsetRectBJ(RectFromLoc(Location(-10,-20),Location(30,40)),3,4);CreateUnitAtLoc(Player(0),FourCC('n001'),GetRectCenter(gg_rct_区域),0)"
    scripts = tmp_path / "脚本可读文本"
    scripts.mkdir()
    (scripts / "war3map.lua").write_text(source, encoding="utf-8")
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "near", "13 14 0")
    )
    row = json.loads(result.render(as_json=True))["entries"][0]
    assert (row["code"], row["x"], row["y"], row["dist"]) == (
        "n001",
        13.0,
        14.0,
        0.0,
    ) and "gg_rct_区域" in result.render()
    assert script_position_groups(
        MapData(path="synthetic.w3x", name="几何构造", scripts={"war3map.lua": source})
    ) == {"n001": ((13.0, 14.0),)}


def test_unicode_rectangle_names_remain_distinct_under_mutation() -> None:
    source = "gg_rct_甲=Rect(0,0,2,4);gg_rct_乙=Rect(10,20,30,40);RemoveRect(gg_rct_乙);CreateItemLoc(FourCC('I001'),GetRectCenter(gg_rct_甲))"
    assert script_placements(source, lua=True) == [("I001", 1.0, 2.0, "item")]
    assert script_rectangles(source, lua=True) == [("gg_rct_甲", 0.0, 0.0, 2.0, 4.0)]


@pytest.mark.parametrize(
    "name",
    [
        "gg_rct_区 域",
        "gg_rct_ 区域",
        "X.gg_rct_区域",
        "gg_rct_区域[1]",
        "gg_rct_区域+1",
    ],
)
def test_region_reference_never_merges_unrelated_tokens(name: str) -> None:
    assert rectangle_name(name) is None
