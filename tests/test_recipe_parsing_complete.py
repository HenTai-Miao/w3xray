"""Recipe coverage follows source operations, argument positions and quantities."""

from collections import Counter
import csv
from pathlib import Path

import pytest

from gametool.api import recipes_from_map
from gametool.item_relation_recipes import build_recipe_item_relations
from gametool.item_relation_models import ItemRelationIndex
from gametool.item_relation_exports import format_item_acquisition_tsv
from gametool.map_data import MapData
from gametool.pack_query_cli import _query_recipe, _query_synth, load_formulas
from gametool.script_object_literals import literal_object_code
from gametool.script_recipes import scan_formulas
from gametool.script_scan import _codes_in, scan_recipes


def test_single_material_upgrade_and_same_code_recharge_are_retained() -> None:
    script = """function Upgrade takes nothing returns nothing
call RemoveItem(GetItemOfTypeFromUnitBJ(u, 'I001'))
call UnitAddItemById(u, 'I002')
call RemoveItem(GetItemOfTypeFromUnitBJ(u, 'I002'))
call UnitAddItemById(u, 'I002')
endfunction"""
    assert [(row.ingredients, row.result) for row in scan_recipes(script)] == [
        (["I001"], "I002"),
        (["I002"], "I002"),
    ]


def test_lua_single_line_distinct_settlements_keep_offsets_and_quantities() -> None:
    consume = "RemoveItem(GetItemOfTypeFromUnitBJ(u, FourCC('I001')));"
    output = 'UnitAddItemById(u, FourCC("I002"));'
    script = "function Forge() " + (consume * 2 + output) * 2 + "end"
    rows = scan_recipes(script, source="war3map.lua")
    assert len(rows) == 2
    assert all(
        row.ingredients == ["I001", "I001"] and row.func == "Forge" for row in rows
    )
    assert rows[0].offset != rows[1].offset
    assert all(row.line == 1 and "RemoveItem" in row.evidence for row in rows)
    md = MapData(path="sample.w3x", name="sample", scripts={"war3map.lua": script})
    assert len(recipes_from_map(md)) == 2
    assert len(build_recipe_item_relations(md)) == 2


def test_argument_positions_ignore_unit_codes_and_nested_consumed_creations() -> None:
    script = """function Forge takes nothing returns nothing
call UnitRemoveItem(CreateUnit(p, 'hfoo', 0, 0, 0), CreateItem('I001', 0, 0))
call UnitAddItemById(CreateUnit(p, 'hpea', 0, 0, 0), 'I002')
call RemoveItem(CreateItem('I003', 0, 0))
call UnitAddItemByIdSwapped('I004', CreateUnit(p, 'hkni', 0, 0, 0))
endfunction"""
    assert [(row.ingredients, row.result) for row in scan_recipes(script)] == [
        (["I001"], "I002"),
        (["I003"], "I004"),
    ]


def test_lookup_without_consumption_and_similar_function_names_are_not_recipes() -> (
    None
):
    script = """function F takes nothing returns nothing
call GetItemOfTypeFromUnitBJ(u, 'I001')
call GetItemOfTypeFromUnitBJ(u, 'I002')
call FakeRemoveItem(GetItemOfTypeFromUnitBJ(u, 'I003'))
call UnitAddItemById(u, 'I004')
endfunction"""
    assert scan_recipes(script) == []


def test_multiline_removals_and_creations_retain_full_source_evidence() -> None:
    script = """function F takes nothing returns nothing
call RemoveItem(
    GetItemOfTypeFromUnitBJ(u,
        $49303031))
call UnitAddItemById(
    u, 1227894834)
endfunction"""
    (recipe,) = scan_recipes(script, source="war3map.j")
    assert (recipe.ingredients, recipe.result, recipe.line) == (["I001"], "I002", 5)
    assert "$49303031" in recipe.evidence and "1227894834" in recipe.evidence


def test_lua_scopes_do_not_leak_into_siblings_or_global_code() -> None:
    script = """function Unfinished()
  RemoveItem(CreateItem(FourCC('I001'), 0, 0))
end
UnitAddItemById(u, FourCC('I002'))
function Other()
  UnitAddItemById(u, FourCC('I003'))
end"""
    assert scan_recipes(script, source="war3map.lua") == []


def test_nested_anonymous_scope_preserves_outer_state_without_mixing_it() -> None:
    script = """function Outer()
  RemoveItem(CreateItem(FourCC('I001'), 0, 0))
  register(function()
    RemoveItem(CreateItem(FourCC('I003'), 0, 0))
    UnitAddItemById(u, FourCC('I004'))
  end)
  UnitAddItemById(u, FourCC('I002'))
end"""
    rows = scan_recipes(script, source="war3map.lua")
    assert [(row.ingredients, row.result) for row in rows] == [
        (["I003"], "I004"),
        (["I001"], "I002"),
    ]
    assert rows[0].func.startswith("<匿名@") and rows[1].func == "Outer"


def test_jass_function_references_do_not_open_fake_recipe_scopes() -> None:
    script = """function F takes nothing returns nothing
call RemoveItem(GetItemOfTypeFromUnitBJ(u, 'I001'))
call TriggerAddAction(t, function Other)
call UnitAddItemById(u, 'I002')
endfunction"""
    (recipe,) = scan_recipes(script, source="war3map.j")
    assert recipe.func == "F" and recipe.ingredients == ["I001"]


def test_conditional_recipe_confidence_survives_relation_building() -> None:
    script = """function F takes nothing returns nothing
if can_forge then
call RemoveItem(GetItemOfTypeFromUnitBJ(u, 'I001'))
call UnitAddItemById(u, 'I002')
endif
endfunction"""
    (recipe,) = scan_recipes(script, source="war3map.j")
    assert recipe.confidence == "可推断"
    md = MapData(path="sample.w3x", name="sample", scripts={"war3map.j": script})
    assert build_recipe_item_relations(md)[0].confidence.value == "可推断"


def test_fourcc_wrappers_count_each_source_occurrence_once() -> None:
    assert Counter(_codes_in("FourCC('I001') + FourCC('I001') + 'I002'")) == {
        "I001": 2,
        "I002": 1,
    }


@pytest.mark.parametrize(
    "value",
    [
        "'I001'",
        "FourCC('I001')",
        'FourCC("I001")',
        "FourCC([=[I001]=])",
        "$49303031",
        "0x49303031",
        "1227894833",
    ],
)
def test_literal_forms_are_shared_with_spatial_queries(value: str) -> None:
    assert literal_object_code(value) == "I001"


@pytest.mark.parametrize(
    "value",
    [
        "FourCC(variable)",
        "FourCC('I001') + 1",
        "'I001' + 1",
        "FourCC('汉字汉字')",
        "0x100000000",
        "GetRandomInt(1, 2)",
    ],
)
def test_nonliteral_or_nonbyte_object_codes_are_not_guessed(value: str) -> None:
    assert literal_object_code(value) == ""


def test_literal_codes_ignore_redundant_leading_zeroes_without_digit_caps() -> None:
    assert literal_object_code("0" * 5000 + "1227894833") == "I001"
    assert literal_object_code("0x" + "0" * 5000 + "49303031") == "I001"


def test_formulas_keep_exact_large_counts_duplicate_materials_and_positive_cheese() -> (
    None
):
    script = """function Declare()
YDWENewItemsFormula(
    FourCC('I001'), 9007199254740993,
    FourCC('I001'), 2,
    FourCC('ches'), 1,
    variable_placeholder, 0,
    FourCC('I002'))
end"""
    (formula,) = scan_formulas(script, source="war3map.lua")
    assert formula.ingredients == (("I001", 9007199254740995), ("ches", 1))
    assert (formula.result, formula.func, formula.source, formula.line) == (
        "I002",
        "Declare",
        "war3map.lua",
        2,
    )


@pytest.mark.parametrize(
    "count,expected", [("(2)", 2), ("2.0", 2), ("2e3", 2000), ("0x10", 16), ("$10", 16)]
)
def test_formula_counts_are_integral_without_float_conversion(
    count: str, expected: int
) -> None:
    (formula,) = scan_formulas(f"call YDWENewItemsFormula('I001', {count}, 'I002')")
    assert formula.ingredients == (("I001", expected),)


@pytest.mark.parametrize(
    "tail",
    [
        "'I003', variable, 'I002'",
        "'I003', 1.5, 'I002'",
        "dynamic_code, 1, 'I002'",
        "'I003', 1, dynamic_code",
        "'I003', 'I002'",
    ],
)
def test_incomplete_formula_does_not_become_a_partial_confirmed_recipe(
    tail: str,
) -> None:
    assert scan_formulas("call YDWENewItemsFormula('I001', 2, " + tail + ")") == []


def test_formula_examples_comments_and_function_definitions_are_not_calls() -> None:
    script = """-- YDWENewItemsFormula('I001', 1, 'I002')
local example = [=[YDWENewItemsFormula('I001', 1, 'I002')]=]
function YDWENewItemsFormula(material, count, result) end
"""
    assert scan_formulas(script, source="war3map.lua") == []


def test_raw_formula_and_legacy_index_mirrors_merge_without_losing_calls(
    tmp_path: Path,
) -> None:
    scripts = tmp_path / "脚本可读文本"
    scripts.mkdir()
    formula = "call YDWENewItemsFormula('I001', 3, 'I002')"
    (scripts / "war3map.j").write_text(formula + "\n" + formula, encoding="utf-8")
    with (tmp_path / "脚本调用参数索引.tsv").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        writer = csv.writer(stream, delimiter="\t")
        for line in (1, 2):
            for argument in (1, 2, 3):
                writer.writerow(
                    ["war3map.j", line, "F", "YDWENewItemsFormula", argument, formula]
                )
        writer.writerow(
            [
                "war3map.j",
                3,
                "F",
                "YDWENewItemsFormula",
                1,
                "call YDWENewItemsFormula('I003', 4, 'I004')",
            ]
        )
    assert load_formulas(tmp_path) == [
        ("I002", [("I001", 3)]),
        ("I002", [("I001", 3)]),
        ("I004", [("I003", 4)]),
    ]


def test_recipe_and_synth_query_read_wct_lua_and_old_index(tmp_path: Path) -> None:
    scripts = tmp_path / "脚本可读文本"
    scripts.mkdir()
    (tmp_path / "地图信息.txt").write_text("脚本语言：Lua\n", encoding="utf-8")
    (scripts / "war3map.wct(自定义代码).txt").write_text(
        'YDWENewItemsFormula(FourCC([=[I001]=]), 9007199254740993, FourCC("I002"))',
        encoding="utf-8",
    )
    (tmp_path / "脚本调用参数索引.tsv").write_text(
        "call YDWENewItemsFormula('I003', 4, 'I004')\n", encoding="utf-8"
    )
    assert "9007199254740993" in "\n".join(_query_recipe(tmp_path, "I001", 0))
    assert len(_query_synth(tmp_path, "", 0)) == 2


def test_multiline_formula_survives_argument_index_without_original_script(
    tmp_path: Path,
) -> None:
    # The summary has only the first line; the complete arguments are retained.
    with (tmp_path / "脚本调用参数索引.tsv").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        writer = csv.writer(stream, delimiter="\t")
        for position, argument in enumerate(
            ("'I,01'", "'+9007199254740993", "'ches'", "'-1", "'I002'"), 1
        ):
            writer.writerow(
                [
                    "war3map.j",
                    1,
                    "F",
                    "YDWENewItemsFormula",
                    position,
                    argument,
                    "",
                    "",
                    "",
                    "",
                    "call YDWENewItemsFormula(",
                ]
            )
    assert load_formulas(tmp_path) == [("I002", [("I,01", 9007199254740993)])]


def test_recipes_have_no_enumeration_cap() -> None:
    script = (
        "function F() "
        + "\n".join(
            f"RemoveItem(CreateItem(FourCC('I{i:03x}'),0,0)); UnitAddItemById(u,FourCC('R{i:03x}'))"
            for i in range(1500)
        )
        + " end"
    )
    rows = scan_recipes(script, source="war3map.lua")
    assert len(rows) == 1500
    assert rows[-1].result == "R5db" and rows[-1].ingredients == ["I5db"]


def test_synth_preserves_same_materials_with_different_quantities(
    tmp_path: Path,
) -> None:
    scripts = tmp_path / "脚本可读文本"
    scripts.mkdir()
    (scripts / "war3map.j").write_text(
        "call YDWENewItemsFormula('I001', 2, 'I002')\n"
        "call YDWENewItemsFormula('I001', 3, 'I002')\n",
        encoding="utf-8",
    )
    assert len(_query_synth(tmp_path, "", 0)) == 2
    assert len(_query_recipe(tmp_path, "I002", 0)) == 2


def test_unresolved_consumption_stays_visible_through_export_and_query(
    tmp_path: Path,
) -> None:
    script = """function F takes nothing returns nothing
call RemoveItem(GetItemOfTypeFromUnitBJ(u, 'I001'))
call RemoveItem(runtime_item)
call UnitAddItemById(u, 'I002')
endfunction"""
    md = MapData(path="sample.w3x", name="sample", scripts={"war3map.j": script})
    relations = build_recipe_item_relations(md)
    (tmp_path / "掉落与获取关系.tsv").write_text(
        format_item_acquisition_tsv(ItemRelationIndex.build(relations)),
        encoding="utf-8",
    )
    assert relations[0].confidence.value == "可推断"
    assert "所列材料未必完整" in relations[0].unresolved_reason
    for lines in (_query_recipe(tmp_path, "I002", 0), _query_synth(tmp_path, "", 0)):
        assert "可推断" in "\n".join(lines)
        assert "所列材料未必完整" in "\n".join(lines)


def test_oversized_argument_position_does_not_break_legacy_summary_query(
    tmp_path: Path,
) -> None:
    with (tmp_path / "脚本调用参数索引.tsv").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        csv.writer(stream, delimiter="\t").writerow(
            [
                "war3map.j",
                1,
                "F",
                "YDWENewItemsFormula",
                "9" * 5000,
                "'I001'",
                "",
                "",
                "",
                "",
                "call YDWENewItemsFormula('I001',2,'I002')",
            ]
        )
    assert load_formulas(tmp_path) == [("I002", [("I001", 2)])]
