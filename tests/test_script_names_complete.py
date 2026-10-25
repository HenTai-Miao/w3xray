"""Qualified Lua names ignore token gaps without losing source identity."""

from pathlib import Path

import pytest

from gametool import pack_query_cli as queries
from gametool.guide_report import format_guide_report
from gametool.map_data import MapData
from gametool.pack_query_options import PackQueryCliOptions
from gametool.pack_query_placements import script_placements, script_rectangles
from gametool.script_names import name_before, qualified_name
from gametool.script_object_literals import literal_object_code
from gametool.script_recipes import scan_recipes
from gametool.script_scan import scan_object_refs
from gametool.script_scopes import script_structure
from gametool.script_trigger_acquisition import trigger_acquisitions
from tests.test_script_multivalue_complete import _GRANT, _IDS, _codes, _script

_GAPS = (
    " ",
    "\t",
    "\n",
    "\r\n",
    "-- comment\n",
    "--[[ . : function Fake() end ]]",
    "--[==[ . : ]==]",
)


@pytest.mark.parametrize("gap", _GAPS)
@pytest.mark.parametrize("assignment", [False, True])
def test_member_getters_use_complete_names_across_token_gaps(
    gap: str, assignment: bool
) -> None:
    name = f"Rewards{gap}.{gap}Id"
    definition = f"{name}=function()" if assignment else f"function {name}()"
    helpers = "Rewards={}; " + definition + " return FourCC('I001') end"
    assert _codes(helpers, f"CreateItem({name}(),0,0)") == ["I001"]
    functions = script_structure(helpers, lua=True).functions
    assert len(functions) == 1 and functions[0].name == "Rewards.Id"
    assert (
        functions[0].complete
        and helpers[functions[0].end - 3 : functions[0].end] == "end"
    )


@pytest.mark.parametrize("gap", _GAPS)
def test_methods_keep_the_implicit_self_argument(gap: str) -> None:
    name = f"Rewards{gap}:{gap}Grant"
    helpers = f"Rewards={{}}; function {name}(id) CreateItem(id,0,0) end"
    assert _codes(helpers, f"{name}(FourCC('I002'))") == ["I002"]


@pytest.mark.parametrize("gap", _GAPS)
def test_member_values_and_function_aliases_share_canonical_symbols(gap: str) -> None:
    member = f"Rewards{gap}.{gap}Value"
    getter = f"Rewards{gap}.{gap}Id"
    helpers = "Rewards={}; function Rewards.Id(id) return id end"
    action = f"{member}=FourCC('I001'); local alias={getter}; local value={member}; CreateItem(alias(value),0,0)"
    assert _codes(helpers, action) == ["I001"]


@pytest.mark.parametrize("gap", _GAPS)
def test_all_global_native_registrations_and_selectors_keep_offsets(gap: str) -> None:
    def native(name: str) -> str:
        return f"_G{gap}.{gap}{name}"

    text = (
        f"function Action() {native('CreateItem')}({native('FourCC')}('I001'),1.25,-2.5) end\n"
        f"local t={native('CreateTrigger')}(); "
        f"{native('TriggerRegisterAnyUnitEventBJ')}(t,EVENT_PLAYER_UNIT_DEATH); "
        f"{native('TriggerAddCondition')}(t,{native('Condition')}(function() return {native('GetUnitTypeId')}({native('GetDyingUnit')}())=={native('FourCC')}('n001') end)); "
        f"{native('TriggerAddAction')}(t,Action)"
    )
    rows = trigger_acquisitions(text, lua=True)
    assert len(rows) == 1 and rows[0].item_code == "I001"
    row = rows[0]
    assert row.unit_codes == ("n001",)
    assert text[row.offset : row.offset + len(row.expression)] == row.expression
    assert row.line == text.count("\n", 0, row.offset) + 1
    assert script_placements(text, lua=True) == [("I001", 1.25, -2.5, "item")]


@pytest.mark.parametrize("gap", _GAPS)
def test_standard_library_members_and_aliases_accept_token_gaps(gap: str) -> None:
    action = f"local unpack=table{gap}.{gap}unpack; Grant(unpack({{Ids()}}))"
    assert _codes(_IDS + _GRANT, action) == ["I001", "I002", "I003"]


@pytest.mark.parametrize(
    "receiver", ["Custom . ", "Custom : ", "Tables[which] . ", "(GetTable()) . "]
)
def test_member_suffix_never_masquerades_as_a_global_native(receiver: str) -> None:
    action = f"{receiver}CreateItem(FourCC('I001'),1,2)"
    assert _codes("", action) == []
    assert script_placements(action, lua=True) == []
    assert not scan_object_refs(action, lua=True)["物品"]


def test_custom_member_named_like_native_is_followed_as_a_source_helper() -> None:
    helpers = (
        "Custom={}; function Custom . CreateItem(id) _G . CreateItem(id,10,20) end"
    )
    assert _codes(helpers, "Custom . CreateItem(FourCC('I001'))") == ["I001"]


@pytest.mark.parametrize("assignment", ["local _G={};", "_G={};"])
def test_shadowed_global_table_is_not_assumed_to_hold_natives(assignment: str) -> None:
    action = assignment + " _G --[[shadow]] . CreateItem(FourCC('I001'),1,2)"
    assert _codes("", action) == []
    assert script_placements(action, lua=True) == []


@pytest.mark.parametrize("assignment", ["local _G={};", "_G={};"])
def test_shadowed_global_table_does_not_supply_nested_coordinates_or_codes(
    assignment: str,
) -> None:
    text = (
        assignment
        + " CreateItemLoc(FourCC('I001'),_G . Location(1,2));"
        + " CreateItem(_G . FourCC('I001'),1,2); gg_rct_Test=_G . Rect(-1,-2,3,4)"
    )
    assert script_placements(text, lua=True) == []
    assert script_rectangles(text, lua=True) == []


@pytest.mark.parametrize("gap", _GAPS)
def test_recipe_members_and_global_wrappers_keep_source_evidence(gap: str) -> None:
    prefix = f"_G{gap}.{gap}"
    text = (
        f"function Forge{gap}.{gap}Merge() "
        f"{prefix}RemoveItem({prefix}GetItemOfTypeFromUnitBJ(u,{prefix}FourCC('I001'))); "
        f"{prefix}UnitAddItemById(u,{prefix}FourCC('I002')) end"
    )
    rows = scan_recipes(text, source="war3map.lua")
    assert len(rows) == 1
    row = rows[0]
    assert (
        row.ingredients == ["I001"]
        and row.result == "I002"
        and row.func == "Forge.Merge"
    )
    assert text[row.offset :].startswith(prefix + "UnitAddItemById")
    assert prefix + "RemoveItem" in row.evidence


def test_custom_member_native_names_are_not_used_as_recipe_operations() -> None:
    text = "function F() Custom . RemoveItem(CreateItem(FourCC('I001'),0,0)); Custom . UnitAddItemById(u,FourCC('I002')) end"
    assert scan_recipes(text, source="war3map.lua") == []


def test_global_location_and_rectangles_accept_comment_gaps() -> None:
    text = "_G --[[a]] . CreateItemLoc(_G . FourCC('I001'),_G --[[b]] . Location(1.25,-2.5)); gg_rct_Test=_G --[[c]] . Rect(-1,-2,3,4)"
    assert script_placements(text, lua=True) == [("I001", 1.25, -2.5, "item")]
    assert script_rectangles(text, lua=True) == [("gg_rct_Test", -1.0, -2.0, 3.0, 4.0)]


@pytest.mark.parametrize("raw", ["'I001'", '"I001"', "[=[I001]=]"])
def test_fourcc_literal_decoder_accepts_global_member_comment_gaps(raw: str) -> None:
    assert literal_object_code(f"_G --[[x]] . FourCC --[[y]] ({raw})") == "I001"


@pytest.mark.parametrize("raw", ["A .. B", "A . 3B", "A : : B", "A[B]", "'A.B'", "A B"])
def test_invalid_or_dynamic_names_are_never_joined_into_static_symbols(
    raw: str,
) -> None:
    assert qualified_name(raw) is None


def test_long_gaps_and_deep_name_chains_have_no_empirical_ceiling() -> None:
    gap = " " * 12000
    name = gap.join(["Layer"] * 2)  # Separate identifiers stay separate.
    assert qualified_name(name) is None
    for name in ("Layer" + gap + "." + gap + "Id", ".".join(["Layer"] * 1200 + ["Id"])):
        compact = name.replace(" ", "")
        assert qualified_name(name) == compact
        assert name_before(name, len(name)) == (0, compact)
        structure = script_structure(
            f"function {name}() return 1 end; {name}()", lua=True
        )
        assert structure.functions[0].name == compact
        assert [call.name for call in structure.calls] == [compact]


@pytest.mark.parametrize(
    "command,query",
    [
        ("where", "I001"),
        ("drop", "I001"),
        ("where", "n001"),
        ("drop", "n001"),
        ("cmd", "-test"),
    ],
)
def test_queries_include_member_helpers_with_original_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str, query: str
) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")
    text = _script(
        "Rewards={}; function Rewards --[[def]] . Id() return _G . FourCC('I001') end",
        "_G . CreateItem(Rewards --[[call]] . Id(),1.25,-2.5)",
    )
    scripts = tmp_path / "脚本可读文本"
    scripts.mkdir()
    (scripts / "war3map.lua").write_text(text, encoding="utf-8")
    output = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), command, query)
    ).render()
    assert "I001" in output and "Rewards.Id" in output and "--[[call]]" in output


def test_near_and_guide_share_global_member_placement_and_acquisition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")
    text = _script("", "_G --[[global]] . CreateItem(_G . FourCC('I001'),1.25,-2.5)")
    scripts = tmp_path / "脚本可读文本"
    scripts.mkdir()
    (scripts / "war3map.lua").write_text(text, encoding="utf-8")
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "near", "1.25 -2.5 1")
    )
    assert "I001" in result.render()
    output = format_guide_report(
        MapData(path="synthetic.w3x", name="成员名称", scripts={"war3map.lua": text}),
        "drops",
    )
    assert "I001[I001]" in output and "_G --[[global]] . CreateItem" in output
