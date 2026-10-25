"""Typed static geometry, complete contexts, and explicit possible mutation edges."""

import json
from pathlib import Path

import pytest

from gametool import pack_query_cli as queries
from gametool.map_data import MapData
from gametool.pack_query_options import PackQueryCliOptions
from gametool.pack_query_placements import script_placements, script_rectangles
from gametool.placement_positions import script_position_groups
from gametool.script_function_graph import script_functions
from gametool.script_placement_analysis import analyze_script_placements
from gametool.script_rectangle_analysis import analyze_script_rectangles

_POINT = (12345.6787109375, -9876.5439453125)
_LOCATION = f"Location({_POINT[0]!r},{_POINT[1]!r})"
_RECT = "Rect(-10.25,-20.5,30.75,40.125)"
_BOUNDS = (-10.25, -20.5, 30.75, 40.125)


@pytest.mark.parametrize(
    "body",
    [
        f"CreateItemLoc(FourCC('I001'),{_LOCATION})",
        f"local p={_LOCATION};CreateItemLoc(FourCC('I001'),p)",
        f"local p={_LOCATION};local q=p;CreateItemLoc(FourCC('I001'),q)",
        f"function P() return {_LOCATION} end CreateItemLoc(FourCC('I001'),P())",
        f"function P() return {_LOCATION} end local Q=P;CreateItemLoc(FourCC('I001'),Q())",
        f"function Spawn(id,p) CreateItemLoc(id,p) end Spawn(FourCC('I001'),{_LOCATION})",
        f"function P(x,y) return Location(x,y) end CreateItemLoc(FourCC('I001'),P({_POINT[0]},{_POINT[1]}))",
        f"function Spawn(id,p) local q=p;CreateItemLoc(id,q) end Spawn(FourCC('I001'),{_LOCATION})",
        f"function Spawn(id,...) CreateItemLoc(id,...) end Spawn(FourCC('I001'),{_LOCATION})",
        f"function Spawn(...) CreateItemLoc(...) end Spawn(FourCC('I001'),{_LOCATION})",
        f"function Pair() return FourCC('I001'),{_LOCATION} end CreateItemLoc(Pair())",
        f"function Pair() return FourCC('I001'),{_LOCATION} end local id,p=Pair();CreateItemLoc(id,p)",
        f"local id,p=FourCC('I001'),{_LOCATION};CreateItemLoc(id,p)",
        f"local C=Location;CreateItemLoc(FourCC('I001'),C({_POINT[0]},{_POINT[1]}))",
        f"local T={{}};T.p={_LOCATION};CreateItemLoc(FourCC('I001'),T.p)",
        f"local T={{}};function T.P() return {_LOCATION} end CreateItemLoc(FourCC('I001'),T.P())",
        f"local T={{}};function T:Spawn(id,p) CreateItemLoc(id,p) end T:Spawn(FourCC('I001'),{_LOCATION})",
        f"CreateItemLoc(FourCC('I001'),select(2,0,{_LOCATION}))",
        f"CreateItemLoc(FourCC('I001'),table.unpack({{{_LOCATION}}}))",
    ],
)
def test_static_locations_survive_complete_value_paths(body: str) -> None:
    analysis = analyze_script_placements(body, lua=True)
    assert [row.row() for row in analysis.placements] == [("I001", *_POINT, "item")]
    assert not analysis.diagnostics


@pytest.mark.parametrize("lua", [False, True])
def test_jass_and_lua_geometry_getters_and_parameters(lua: bool) -> None:
    if lua:
        source = f"function P() return {_LOCATION} end function S(id,p) CreateItemLoc(id,p) end S(FourCC('I001'),P())"
    else:
        source = f"function P takes nothing returns location\nreturn {_LOCATION}\nendfunction\nfunction S takes integer id, location p returns nothing\ncall CreateItemLoc(id,p)\nendfunction\ncall S('I001',P())"
    assert script_placements(source, lua=lua) == [("I001", *_POINT, "item")]


@pytest.mark.parametrize("api", ["CreateItemLoc", "CreateUnitAtLoc"])
def test_location_native_unit_and_item_signatures(api: str) -> None:
    unit = api == "CreateUnitAtLoc"
    args = (
        f"Player(0),FourCC('n001'),{_LOCATION},90"
        if unit
        else f"FourCC('I001'),{_LOCATION}"
    )
    assert script_placements(f"{api}({args})", lua=True) == [
        ("n001" if unit else "I001", *_POINT, "unit" if unit else "item")
    ]


@pytest.mark.parametrize(
    ("reader", "expected"),
    [
        ("GetRectMinX", -10.25),
        ("GetRectMinY", -20.5),
        ("GetRectMaxX", 30.75),
        ("GetRectMaxY", 40.125),
        ("GetRectCenterX", 10.25),
        ("GetRectCenterY", 9.8125),
    ],
)
def test_rect_projections_keep_precision(reader: str, expected: float) -> None:
    source = f"local r={_RECT};CreateItem(FourCC('I001'),{reader}(r),0)"
    assert script_placements(source, lua=True) == [("I001", expected, 0.0, "item")]


def test_location_projections_and_arithmetic() -> None:
    source = f"local p={_LOCATION};CreateItem(FourCC('I001'),GetLocationX(p)+0.5,GetLocationY(p)-0.25)"
    assert script_placements(source, lua=True) == [
        ("I001", _POINT[0] + 0.5, _POINT[1] - 0.25, "item")
    ]


@pytest.mark.parametrize("value", [5e-324, 1e308, -1e308])
def test_rect_center_avoids_overflow_and_subnormal_underflow(value: float) -> None:
    source = f"local r=Rect({value!r},{value!r},{value!r},{value!r});CreateItemLoc(FourCC('I001'),GetRectCenter(r))"
    assert script_placements(source, lua=True) == [("I001", value, value, "item")]


@pytest.mark.parametrize(
    "effect",
    [
        "MoveLocation(q,3,4)",
        "RemoveLocation(q)",
        "Unknown(q)",
        "local M=MoveLocation;M(q,3,4)",
    ],
)
@pytest.mark.parametrize(
    "alias",
    [
        "local q=p",
        "local T={};T.p=p;local q=T.p",
        "function Identity(v) return v end local q=Identity(p)",
    ],
)
def test_possible_location_mutations_and_escapes_never_return_stale_points(
    effect: str, alias: str
) -> None:
    source = f"local p={_LOCATION};{alias};{effect};CreateItemLoc(FourCC('I001'),p)"
    analysis = analyze_script_placements(source, lua=True)
    assert not analysis.placements and "几何句柄" in analysis.diagnostics[0].reason
    assert "偏移" in analysis.diagnostics[0].reason


def test_source_helper_mutation_is_propagated_to_actual_handle() -> None:
    source = f"function Mutate(p) MoveLocation(p,3,4) end local p={_LOCATION};Mutate(p);CreateItemLoc(FourCC('I001'),p)"
    analysis = analyze_script_placements(source, lua=True)
    assert not analysis.placements and "修改" in analysis.diagnostics[0].reason


def test_parallel_multireturn_alias_tracks_second_geometry_value() -> None:
    source = f"function Pair() return 0,{_LOCATION} end local id,p=Pair();local q=p;RemoveLocation(q);CreateItemLoc(FourCC('I001'),p)"
    assert not script_placements(source, lua=True)
    assert (
        "几何句柄" in analyze_script_placements(source, lua=True).diagnostics[0].reason
    )


def test_unrelated_same_coordinates_are_not_aliased() -> None:
    source = f"local p={_LOCATION};local q={_LOCATION};RemoveLocation(q);CreateItemLoc(FourCC('I001'),p)"
    assert script_placements(source, lua=True) == [("I001", *_POINT, "item")]


@pytest.mark.parametrize(
    "source",
    [
        f"local Location=Runtime;CreateItemLoc(FourCC('I001'),{_LOCATION})",
        f"local _G={{}};CreateItemLoc(FourCC('I001'),_G.{_LOCATION})",
        "CreateItemLoc(FourCC('I001'),'Location(1,2)')",
        "CreateItemLoc(FourCC('I001'),RuntimeLocation())",
        "CreateItemLoc(FourCC('I001'),Location(1/0,2))",
        "CreateItemLoc(FourCC('I001'),Location(1))",
        "local T={};T.p=Location(1,2);T={};CreateItemLoc(FourCC('I001'),T.p)",
        "local T={};T.id=FourCC('I001');T={};CreateItemLoc(T.id,Location(1,2))",
    ],
)
def test_unknown_text_nonfinite_or_replaced_geometry_never_becomes_point(
    source: str,
) -> None:
    analysis = analyze_script_placements(source, lua=True)
    assert not analysis.placements and analysis.diagnostics


@pytest.mark.parametrize(
    "source",
    [
        f"gg_rct_Test={_RECT}",
        f"function R() return {_RECT} end gg_rct_Test=R()",
        f"local R=Rect;gg_rct_Test=R{_RECT.removeprefix('Rect')}",
        f"local r={_RECT};gg_rct_Test=r",
        "function R(a,b,c,d) gg_rct_Test=Rect(a,b,c,d) end R(-10.25,-20.5,30.75,40.125)",
        f"function Set(r) gg_rct_Test=r end Set({_RECT})",
        f"function Pair() return 0,{_RECT} end local n; n,gg_rct_Test=Pair()",
        f"_G . gg_rct_Test={_RECT}",
    ],
)
def test_named_rectangle_getters_parameters_and_aliases(source: str) -> None:
    assert script_rectangles(source, lua=True) == [("gg_rct_Test", *_BOUNDS)]
    assert not analyze_script_rectangles(source, lua=True).diagnostics


@pytest.mark.parametrize(
    "effect",
    [
        "SetRect(r,0,0,1,1)",
        "SetRectFromLoc(r,Location(0,0),Location(1,1))",
        "MoveRectTo(r,0,0)",
        "MoveRectToLoc(r,Location(0,0))",
        "RemoveRect(r)",
        "Unknown(r)",
    ],
)
def test_rect_mutations_removals_and_escapes_are_diagnostic(effect: str) -> None:
    source = f"local r={_RECT};gg_rct_Test=r;{effect};CreateItemLoc(FourCC('I001'),GetRectCenter(r))"
    analysis = analyze_script_rectangles(source, lua=True)
    assert not analysis.rectangles and "几何句柄" in analysis.diagnostics[0].reason
    assert not script_placements(source, lua=True)


def test_named_rectangle_retains_all_distinct_context_bounds() -> None:
    source = "function R(x) gg_rct_Test=Rect(x,-20,x,40) end R(1.25);R(2.5);R(1.25);R(Runtime())"
    analysis = analyze_script_rectangles(source, lua=True)
    assert [r.row() for r in analysis.rectangles] == [
        ("gg_rct_Test", 1.25, -20.0, 1.25, 40.0),
        ("gg_rct_Test", 2.5, -20.0, 2.5, 40.0),
    ]
    assert len(analysis.diagnostics) == 1 and "动态" in analysis.diagnostics[0].reason


def test_constructor_shadowing_and_quoted_rect_examples_are_rejected() -> None:
    source = (
        f'local example="gg_rct_Decoy={_RECT}";local Rect=Runtime;gg_rct_Test={_RECT}'
    )
    assert not script_rectangles(source, lua=True)


def test_parallel_region_diagnostic_keeps_the_complete_rhs() -> None:
    source = (
        "function Pair() return 0,RuntimeRect() end local n;n,gg_rct_Unknown=Pair()"
    )
    analysis = analyze_script_rectangles(source, lua=True)
    assert not analysis.rectangles and len(analysis.diagnostics) == 1
    assert analysis.diagnostics[0].expression == "gg_rct_Unknown=Pair()"


def test_reversed_rect_bounds_remain_evidence_without_projection_guesses() -> None:
    source = "gg_rct_Reverse=Rect(10,20,-10,-20);CreateItemLoc(FourCC('I001'),GetRectCenter(gg_rct_Reverse))"
    assert script_rectangles(source, lua=True) == [
        ("gg_rct_Reverse", 10.0, 20.0, -10.0, -20.0)
    ]
    assert not script_placements(source, lua=True)


def test_1050_geometry_forwarding_levels_use_shared_iterative_contexts() -> None:
    depth = 1050
    source = "\n".join(f"function F{i}(id,p) F{i + 1}(id,p) end" for i in range(depth))
    source += f"\nfunction F{depth}(id,p) CreateItemLoc(id,p) end F0(FourCC('I001'),{_LOCATION})"
    assert script_placements(source, lua=True) == [("I001", *_POINT, "item")]
    functions = script_functions(source, lua=True)
    assert functions.source_contexts() is functions.source_contexts()


def test_1500_locations_and_rectangles_have_no_context_ceiling() -> None:
    count = 1500
    source = "function S(p,r) CreateItemLoc(FourCC('I001'),p);gg_rct_Test=r end\n"
    source += "\n".join(
        f"S(Location({i}.25,-{i}.5),Rect({i},-1,{i + 1},1))" for i in range(count)
    )
    assert len(script_placements(source, lua=True)) == count
    assert len(script_rectangles(source, lua=True)) == count


def test_near_json_and_guide_positions_share_geometry_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")
    source = "function R() return Rect(-20,-30,40,50) end gg_rct_目标=R();CreateUnitAtLoc(Player(0),FourCC('n001'),GetRectCenter(R()),0)"
    scripts = tmp_path / "脚本可读文本"
    scripts.mkdir()
    (scripts / "war3map.lua").write_text(source, encoding="utf-8")
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "near", "10 10 0")
    )
    data = json.loads(result.render(as_json=True))
    entry = next(row for row in data["entries"] if row["code"] == "n001")
    assert (entry["x"], entry["y"], entry["dist"]) == (10.0, 10.0, 0.0)
    assert entry["positions"] == [[10.0, 10.0]] and "gg_rct_目标" in result.render()
    assert script_position_groups(
        MapData(path="synthetic.w3x", name="几何", scripts={"war3map.lua": source})
    ) == {"n001": ((10.0, 10.0),)}


def test_near_discloses_unresolved_named_rectangles_with_full_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")
    source = "gg_rct_Dynamic=RuntimeRect();gg_rct_Other=RuntimeRect()"
    scripts = tmp_path / "脚本可读文本"
    scripts.mkdir()
    (scripts / "war3map.lua").write_text(source, encoding="utf-8")
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "near", "0 0 1")
    )
    assert not json.loads(result.render(as_json=True))["entries"]
    assert all(
        word in result.render()
        for word in (
            "2 条脚本点位诊断",
            "gg_rct_Dynamic",
            "gg_rct_Other",
            "RuntimeRect()",
            "偏移",
        )
    )
