"""Exact ownership remains complete across minification, nesting and exports."""

from __future__ import annotations

import csv
from dataclasses import replace
from io import StringIO
from pathlib import Path

import pytest

from gametool.api import GameObject, MapData
from gametool.item_relation_models import ItemRelationIndex
from gametool.item_relation_scripts import build_script_call_item_relations
from gametool import item_relation_scripts
from gametool import pack_query_cli as queries
from gametool.script_call_argument_index import (
    build_script_call_argument_index,
    format_script_call_argument_index_tsv,
    ScriptCallArgumentIndex,
)
from gametool.script_call_catalog import build_script_call_catalog
from gametool.script_function_index import (
    build_function_lookup,
    build_script_function_index,
    format_script_function_index_tsv,
)
from gametool.script_object_code_occurrence_index import (
    build_script_object_code_occurrence_index,
    format_script_object_code_occurrence_index_tsv,
)
from gametool.script_scopes import ScopeLookup, script_structure
from gametool.script_string_index import build_script_string_index
from gametool.script_trigger_registration_index import (
    build_script_trigger_registration_index,
)
from gametool.script_variable_usage_index import build_script_variable_usage_index


def _map(text: str, lua: bool = True) -> MapData:
    md = MapData(path="synthetic.w3x", name="scope coverage")
    md.scripts = {"war3map.lua" if lua else "war3map.j": text}
    return md


@pytest.mark.parametrize("lua", [True, False])
def test_adjacent_same_line_functions_keep_all_direct_calls_and_exact_ranges(
    lua: bool,
) -> None:
    text = (
        "function Z() One(1); Two(2); end; function A() Other(3); end"
        if lua
        else "private function Z takes nothing returns nothing call One(1) call Two(2) endfunction public function A takes nothing returns nothing call Other(3) endfunction"
    )
    md = _map(text, lua)
    functions = build_script_function_index(md).functions
    assert [
        (row.name, row.called_functions, row.internal_calls) for row in functions
    ] == [("Z", ("One", "Two"), 2), ("A", ("Other",), 1)]
    assert all(row.start_line == row.end_line == 1 for row in functions)
    assert all(row.complete for row in functions)
    lookup = build_function_lookup(functions)
    source = next(iter(md.scripts))
    assert lookup.name_for(source, 1, offset=text.index("Two(")) == "Z"
    assert lookup.name_for(source, 1, offset=text.index("Other(")) == "A"
    arguments = build_script_call_argument_index(md).arguments
    assert [(row.call, row.function) for row in arguments] == [
        ("One", "Z"),
        ("Two", "Z"),
        ("Other", "A"),
    ]


def test_anonymous_callbacks_own_their_calls_literals_and_item_creations() -> None:
    md = _map(
        "function Outer() Register(function() CreateItem(FourCC('I003'),0,0); print('inner') end); print('outer') end"
    )
    rows = build_script_function_index(md).functions
    outer, child = rows
    assert outer.name == "Outer" and child.name.startswith("<匿名@")
    assert child.parent_offset == outer.start_offset
    assert outer.called_functions == ("Register", "print") and outer.object_codes == ()
    assert child.called_functions == ("CreateItem", "print") and child.object_codes == (
        "I003",
    )
    register = next(
        row for row in build_script_call_catalog(md).calls if row.function == "Register"
    )
    assert register.object_codes == () and register.string_args == ()
    arguments = [
        row
        for row in build_script_call_argument_index(md).arguments
        if row.call == "Register"
    ]
    assert len(arguments) == 1 and "I003" in arguments[0].argument
    assert arguments[0].object_codes == () and arguments[0].string_value == ""
    strings = {
        row.value: (row.function, row.call)
        for row in build_script_string_index(md).entries
    }
    assert strings == {"inner": (child.name, "print"), "outer": ("Outer", "print")}
    assert "function" not in {
        row.function for row in build_script_call_catalog(md).calls
    }


def test_callback_argument_positions_survive_masking_nested_function_bodies() -> None:
    md = _map(
        "function F() Register('before',function() print('inside') end,'after') end"
    )
    rows = [
        row
        for row in build_script_call_argument_index(md).arguments
        if row.call == "Register"
    ]
    assert [row.position for row in rows] == [1, 2, 3]
    assert [row.string_value for row in rows] == ["before", "", "after"]


def test_nested_named_functions_resolve_calls_inside_arguments_and_keep_parent_identity() -> (
    None
):
    md = _map(
        "function Factory() local function Step() Step(); end; Use(Step()); end; function Other() local function Step() end; Step(); end"
    )
    rows = build_script_function_index(md).functions
    factory, step_one, other, step_two = rows
    assert [row.name for row in rows] == ["Factory", "Step", "Other", "Step"]
    assert step_one.inbound_calls == step_two.inbound_calls == 1
    assert (
        step_one.parent_offset == factory.start_offset
        and step_two.parent_offset == other.start_offset
    )
    assert factory.called_functions == ("Use",) and step_one.called_functions == (
        "Step",
    )


def test_same_named_definitions_in_other_sources_do_not_inflate_inbound_counts() -> (
    None
):
    md = _map("function Target() end; function Caller() Wrap(Target()) end")
    md.scripts["other.lua"] = "function Target() end"
    rows = build_script_function_index(md).functions
    assert {(row.source, row.name): row.inbound_calls for row in rows} == {
        ("other.lua", "Target"): 0,
        ("war3map.lua", "Target"): 1,
        ("war3map.lua", "Caller"): 0,
    }


def test_same_scope_duplicate_definitions_disclose_ambiguous_calls() -> None:
    md = _map("local function F() end; local function F() end; F()")
    rows = build_script_function_index(md).functions
    assert len(rows) == 2 and all(
        row.inbound_calls == 0 and row.ambiguous_calls == 1 for row in rows
    )
    table = list(
        csv.reader(
            StringIO(format_script_function_index_tsv(build_script_function_index(md))),
            delimiter="\t",
        )
    )
    assert "歧义调用数" in table[0] and all(row[-1] == "1" for row in table[1:])


@pytest.mark.parametrize(
    "definition,call",
    [("obj.run", "obj.run"), ("obj:run", "obj:run"), ("obj:run", "obj.run")],
)
def test_qualified_and_method_names_keep_scope_and_inbound_identity(
    definition: str, call: str
) -> None:
    md = _map(f"function {definition}() Work() end; function Init() {call}() end")
    row = next(
        row
        for row in build_script_function_index(md).functions
        if row.name == definition
    )
    assert row.inbound_calls == 1 and row.called_functions == ("Work",)
    assert call in {row.function for row in build_script_call_catalog(md).calls}


@pytest.mark.parametrize("newline", ["\n", "\r", "\r\n"])
def test_scopes_preserve_offsets_and_lines_for_all_source_newlines(
    newline: str,
) -> None:
    text = newline.join(("function F()", "print('text')", "end"))
    md = _map(text)
    structure = script_structure(text, lua=True)
    (scope,) = structure.functions
    assert (scope.start, scope.end, scope.start_line, scope.end_line) == (
        0,
        len(text),
        1,
        3,
    )
    (entry,) = build_script_string_index(md).entries
    assert entry.line == 2 and entry.function == "F"


def test_function_ranges_have_no_depth_or_count_ceiling_and_headers_do_not_copy_bodies() -> (
    None
):
    depth = 2200
    text = "local f=" + "function() " * depth + "Leaf(1) " + "end " * depth
    md = _map(text)
    rows = build_script_function_index(md).functions
    assert len(rows) == depth
    assert rows[-1].called_functions == ("Leaf",)
    assert sum(row.internal_calls for row in rows) == 1
    assert {row.summary for row in rows} == {"function()"}
    lookup = build_function_lookup(rows)
    assert (
        lookup.name_for("war3map.lua", 1, offset=text.index("Leaf(")) == rows[-1].name
    )


@pytest.mark.parametrize(
    "lua,text",
    [
        (True, "function Open() Work(1)"),
        (False, "function Open takes nothing returns nothing\ncall Work(1)"),
    ],
)
def test_unclosed_function_is_retained_with_explicit_range_diagnostics(
    lua: bool, text: str
) -> None:
    md = _map(text, lua)
    (row,) = build_script_function_index(md).functions
    assert row.name == "Open" and not row.complete and row.called_functions == ("Work",)
    assert row.end_offset == len(text)
    assert "未闭合" in format_script_function_index_tsv(build_script_function_index(md))


@pytest.mark.parametrize(
    "text",
    [
        "local text='function Fake() end'",
        "--[[function Fake() end]]",
        "local text=[==[function Fake() end]==]",
    ],
)
def test_function_like_data_does_not_create_scopes_or_calls(text: str) -> None:
    structure = script_structure(text, lua=True)
    assert structure.functions == () and structure.calls == ()


def test_nested_trigger_registrations_keep_callback_scope() -> None:
    md = _map(
        "function Init() TriggerAddAction(t,function() TriggerRegisterPlayerChatEvent(other,Player(0),'-inner',true) end) end"
    )
    rows = build_script_trigger_registration_index(md).registrations
    assert rows[0].function == "Init" and rows[1].function.startswith("<匿名@")


def test_object_occurrences_use_actual_positions_and_do_not_mix_neighbor_functions() -> (
    None
):
    md = _map(
        "function A() CreateItem(FourCC('I001'),0,0) end; function B() RemoveItem(GetItemOfTypeFromUnitBJ(u,FourCC('I001'))) end"
    )
    rows = build_script_object_code_occurrence_index(md).occurrences
    assert [(row.code, row.function, row.context) for row in rows] == [
        ("I001", "A", "CreateItem"),
        ("I001", "B", "GetItemOfTypeFromUnitBJ"),
    ]
    assert rows[0].offset != rows[1].offset
    assert "RemoveItem" not in rows[0].summary and "CreateItem" not in rows[1].summary


def test_comparison_reference_stops_at_then_before_neighbor_creation(
    tmp_path: Path,
) -> None:
    md = _map(
        "function F() if GetItemTypeId(u)==FourCC('I001') then CreateItem(FourCC('I002'),0,0) end end"
    )
    index = build_script_object_code_occurrence_index(md)
    (tmp_path / "脚本对象码出现索引.tsv").write_text(
        format_script_object_code_occurrence_index_tsv(index), encoding="utf-8"
    )
    rows = {row.code: row for row in index.occurrences}
    assert "CreateItem" not in rows["I001"].summary
    assert "作为材料/触发媒介(被检测或移除): 1 处" in "\n".join(
        queries._query_refs(tmp_path, "I001", 0)
    )


def test_variable_names_repeated_on_one_line_keep_each_function_owner() -> None:
    md = _map("function A() print(udg_x) end; function B() print(udg_x) end")
    assert [
        (row.variable, row.function)
        for row in build_script_variable_usage_index(md).usages
    ] == [("udg_x", "A"), ("udg_x", "B")]


def test_identical_single_line_item_calls_keep_offsets_counts_and_coordinates() -> None:
    md = _map(
        "function F() CreateItem(FourCC('I001'),1,2); CreateItem(FourCC('I001'),1,2) end"
    )
    item = GameObject("物品", "w3t", "I001", "ratf", "物品", True)
    md.objects = {"物品": [item]}
    md.obj_index = {"I001": item}
    rows = build_script_call_item_relations(md)
    assert len(rows) == len(ItemRelationIndex.build(rows).records) == 2
    assert all(row.x == 1 and row.y == 2 for row in rows)
    assert rows[0].evidence.offset != rows[1].evidence.offset


def test_nested_consumed_item_construction_is_not_exported_as_independent_reward() -> (
    None
):
    md = _map("function F() RemoveItem(CreateItem(FourCC('I001'),0,0)) end")
    assert build_script_call_item_relations(md) == ()


def test_index_only_coordinate_and_formula_readers_accept_appended_offsets(
    tmp_path: Path,
) -> None:
    md = _map(
        "function F() CreateItem(FourCC('I001'),1,2); CreateItem(FourCC('I001'),1,2); YDWENewItemsFormula(FourCC('I001'),2,FourCC('I002')); YDWENewItemsFormula(FourCC('I001'),2,FourCC('I002')) end"
    )
    table = format_script_call_argument_index_tsv(build_script_call_argument_index(md))
    (tmp_path / "脚本调用参数索引.tsv").write_text(table, encoding="utf-8")
    assert "调用偏移" in table.splitlines()[0]
    assert queries.load_placements(tmp_path) == [("I001", 1.0, 2.0, "item")] * 2
    assert queries.load_formulas(tmp_path) == [("I002", [("I001", 2)])] * 2


def test_scope_lookup_returns_no_owner_in_global_gaps_and_exclusive_ends() -> None:
    lookup = ScopeLookup([(0, 4, "outer"), (1, 3, "inner"), (10, 12, "next")])
    assert [lookup.at(position) for position in (-1, 0, 1, 3, 4, 9, 10, 12)] == [
        None,
        "outer",
        "inner",
        "outer",
        None,
        None,
        "next",
        None,
    ]


@pytest.mark.parametrize(
    "name", ["loop", "exitwhen", "endloop", "endif", "endfunction"]
)
def test_jass_keywords_remain_valid_lua_function_names(name: str) -> None:
    md = _map(f"function {name}() Work() end; {name}()")
    (row,) = build_script_function_index(md).functions
    assert row.name == name and row.inbound_calls == 1
    assert {call.function for call in build_script_call_catalog(md).calls} == {
        "Work",
        name,
    }


def test_legacy_full_line_summaries_do_not_multiply_calls_from_argument_rows(
    tmp_path: Path,
) -> None:
    summary = "call CreateItem('I001',1,2); call CreateItem('I001',1,2); call YDWENewItemsFormula('I001',2,'I002'); call YDWENewItemsFormula('I001',2,'I002')"
    rows = [
        [
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
        ]
    ]
    for name, arguments in [("CreateItem", ("'I001'", "1", "2"))] * 2 + [
        ("YDWENewItemsFormula", ("'I001'", "2", "'I002'"))
    ] * 2:
        rows.extend(
            ["war3map.j", "1", "F", name, str(index), argument, "", "", "", "", summary]
            for index, argument in enumerate(arguments, 1)
        )
    with (tmp_path / "脚本调用参数索引.tsv").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        csv.writer(stream, delimiter="\t").writerows(rows)
    assert queries.load_placements(tmp_path) == [("I001", 1.0, 2.0, "item")] * 2
    assert queries.load_formulas(tmp_path) == [("I002", [("I001", 2)])] * 2


def test_global_statements_after_same_line_function_end_have_no_function_owner() -> (
    None
):
    md = _map("function F() print('inner',udg_x) end; print('global',udg_x)")
    strings = {row.value: row.function for row in build_script_string_index(md).entries}
    assert strings == {"inner": "F", "global": ""}
    variables = [
        (row.variable, row.function)
        for row in build_script_variable_usage_index(md).usages
    ]
    assert variables == [("udg_x", "F"), ("udg_x", "")]
    (row,) = build_script_function_index(md).functions
    assert row.internal_calls == 1


def test_assigned_function_is_indexed_without_a_fake_function_keyword_call() -> None:
    md = _map("local callback = function() Work(1) end; callback()")
    (row,) = build_script_function_index(md).functions
    assert row.name == "callback" and row.inbound_calls == 1
    assert row.called_functions == ("Work",) and row.parent_offset is None
    assert "function" not in {
        row.function for row in build_script_call_catalog(md).calls
    }


def test_global_table_aliases_keep_qualified_names_and_native_semantics() -> None:
    md = _map("function F() end; _G.F(); _G.CreateItem(FourCC('I001'),1,2)")
    (row,) = build_script_function_index(md).functions
    assert row.inbound_calls == 1
    call = next(
        row
        for row in build_script_call_catalog(md).calls
        if row.function == "_G.CreateItem"
    )
    assert call.mechanism == "ObjectID:物品" and call.object_codes == ("I001",)
    (relation,) = build_script_call_item_relations(md)
    assert relation.item.object_id == "I001" and (relation.x, relation.y) == (1, 2)


def test_unresolved_name_binding_is_disclosed_instead_of_reported_as_no_calls() -> None:
    md = _map("function Outer() local function Hidden() end end; Hidden()")
    row = next(
        row for row in build_script_function_index(md).functions if row.name == "Hidden"
    )
    assert row.inbound_calls == 0 and row.ambiguous_calls == 1


def test_fourcc_comments_keep_call_codes_and_exact_occurrence_owner() -> None:
    md = _map("function F() CreateItem(FourCC(-- name\n'I001'),1,2) end")
    row = next(
        row
        for row in build_script_call_catalog(md).calls
        if row.function == "CreateItem"
    )
    assert row.object_codes == ("I001",)
    (entry,) = build_script_object_code_occurrence_index(md).occurrences
    assert entry.function == "F" and entry.context == "CreateItem"


def test_legacy_argument_batches_keep_original_call_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = "function F() CreateItem(FourCC('I001'),1,2); CreateItem(FourCC('I002'),3,4) end"
    md = _map(text)
    parsed = build_script_call_argument_index(md)
    legacy = ScriptCallArgumentIndex(
        tuple(replace(row, call_offset=None, summary=text) for row in parsed.arguments)
    )
    monkeypatch.setattr(
        item_relation_scripts, "build_script_call_argument_index", lambda _map: legacy
    )
    rows = build_script_call_item_relations(md)
    assert [(row.item.object_id, row.x, row.y) for row in rows] == [
        ("I001", 1, 2),
        ("I002", 3, 4),
    ]


def test_unclosed_jass_function_does_not_absorb_the_next_declaration() -> None:
    md = _map(
        "function Broken takes nothing returns nothing\ncall A(1)\nfunction Good takes nothing returns nothing\ncall B(2)\nendfunction",
        False,
    )
    broken, good = build_script_function_index(md).functions
    assert not broken.complete and good.complete
    assert broken.called_functions == ("A",) and good.called_functions == ("B",)
    assert good.parent_offset is None


def test_qualified_global_trigger_api_keeps_native_registration_type() -> None:
    md = _map("function Init() _G.TriggerAddAction(t,Handler) end")
    (row,) = build_script_trigger_registration_index(md).registrations
    assert row.api == "_G.TriggerAddAction" and row.registration_type == "动作"
    assert row.function == "Init"


def test_large_argument_lists_export_one_complete_call_summary_without_repeating_it() -> (
    None
):
    arguments = [f"'value{i}'" for i in range(1800)]
    call = "RegisterText(" + ",".join(arguments) + ")"
    md = _map(call)
    table = list(
        csv.reader(
            StringIO(
                format_script_call_argument_index_tsv(
                    build_script_call_argument_index(md)
                )
            ),
            delimiter="\t",
        )
    )
    assert len(table) == len(arguments) + 1
    assert [row[5] for row in table[1:]] == arguments
    assert [row[10] for row in table[1:] if row[10]] == [call]
    assert {row[-1] for row in table[1:]} == {"0"}


def test_minified_string_reports_keep_exact_literals_without_copying_entire_lines() -> (
    None
):
    md = _map(
        "function F() " + ";".join(f"print('value{i}')" for i in range(1800)) + " end"
    )
    entries = build_script_string_index(md).entries
    assert len(entries) == 1800
    assert [entry.summary for entry in entries] == [f"'value{i}'" for i in range(1800)]
    assert all(entry.function == "F" and entry.call == "print" for entry in entries)
    assert len({entry.offset for entry in entries}) == 1800
