"""Complete return ranges and conservative scalar helper dataflow."""

from pathlib import Path

import pytest

from gametool import pack_query_cli as queries
from gametool.guide_report import format_guide_report
from gametool.map_data import MapData
from gametool.pack_query_options import PackQueryCliOptions
from gametool.script_function_graph import script_functions
from gametool.script_return_index import (
    build_script_return_index,
    format_script_return_index_tsv,
)
from gametool.script_returns import script_returns
from gametool.script_trigger_acquisition import trigger_acquisitions


def _script(helpers: str, action: str, *, lua: bool = True) -> str:
    if lua:
        return (
            helpers
            + f"\nfunction Action() {action} end local t=CreateTrigger() TriggerRegisterAnyUnitEventBJ(t,EVENT_PLAYER_UNIT_DEATH) TriggerRegisterPlayerChatEvent(t,Player(0),'-test',true) TriggerAddCondition(t,Condition(function() return GetUnitTypeId(GetDyingUnit())==FourCC('n001') end)) TriggerAddAction(t,Action)"
        )
    return (
        helpers
        + f"\nfunction Action takes nothing returns nothing {action} endfunction function Check takes nothing returns boolean return GetUnitTypeId(GetDyingUnit())=='n001' endfunction function Init takes nothing returns nothing set t=CreateTrigger() call TriggerRegisterAnyUnitEventBJ(t,EVENT_PLAYER_UNIT_DEATH) call TriggerRegisterPlayerChatEvent(t,Player(0),\"-test\",true) call TriggerAddCondition(t,Condition(function Check)) call TriggerAddAction(t,function Action) endfunction"
    )


def _simple(lua: bool) -> str:
    return _script(
        "function Id() return FourCC('I001') end"
        if lua
        else "function Id takes nothing returns integer return 'I001' endfunction",
        "CreateItem(Id(),0,0)" if lua else "call CreateItem(Id(),0,0)",
        lua=lua,
    )


@pytest.mark.parametrize("lua", [True, False])
def test_inline_returns_have_independent_exact_positions(lua: bool) -> None:
    text = (
        "function F(c) if c then return 1 else return 2 end end"
        if lua
        else "function F takes boolean c returns integer if c then return 1 else return 2 endif endfunction"
    )
    rows = script_returns(text, lua=lua)
    assert [row.expression for row in rows] == ["1", "2"]
    assert all(
        row.line == 1 and text[row.start : row.end] == "return " + row.expression
        for row in rows
    )
    md = MapData(
        path="synthetic.w3x",
        name="返回值测试",
        scripts={"war3map.lua" if lua else "war3map.j": text},
    )
    index = build_script_return_index(md)
    assert len(index.returns) == 2 and all(row.function == "F" for row in index.returns)
    exported = format_script_return_index_tsv(index)
    assert all(len(line.split("\t")) == 14 for line in exported.splitlines())
    assert "偏移\t结束行\t结束偏移\t诊断" in exported


def test_multiline_returns_keep_full_expression_and_crlf_offsets() -> None:
    text = 'function F()\r\n return\r\n FourCC(\r\n  "I001"\r\n )\r\nend'
    (row,) = script_returns(text, lua=True)
    assert row.expression == 'FourCC(\r\n  "I001"\r\n )'
    assert row.line == 2 and row.end_line == 5
    assert text[row.expression_start : row.end] == row.expression


def test_nested_return_function_has_its_own_scope_and_full_parent_expression() -> None:
    text = 'function Outer() return function() return "return fake" end end'
    outer, inner = script_returns(text, lua=True)
    assert outer.expression == 'function() return "return fake" end'
    assert inner.expression == '"return fake"' and inner.owner != outer.owner


def test_comments_strings_and_multiple_values_preserve_return_evidence() -> None:
    text = '-- return 99\nfunction F() local text=[=[return 88]=]; return {a="end",f=function() return 3 end}, FourCC("I001") end'
    rows = script_returns(text, lua=True)
    assert len(rows) == 2
    assert rows[0].first == '{a="end",f=function() return 3 end}'
    assert rows[0].expression.endswith('FourCC("I001")')
    assert rows[1].expression == "3"


def test_complete_index_has_no_return_count_limit() -> None:
    count = 6000
    text = "\n".join(f"function F{i}() return {i} end" for i in range(count))
    md = MapData(path="synthetic.w3x", name="返回值测试", scripts={"war3map.lua": text})
    rows = build_script_return_index(md).returns
    assert len(rows) == count and rows[-1].expression == str(count - 1)
    assert rows[-1].function == f"F{count - 1}"


def test_return_expression_has_no_parenthesis_depth_or_length_cutoff() -> None:
    depth = 1600
    text = (
        "function F() return " + "(" * depth + 'FourCC("I001")' + ")" * depth + " end"
    )
    (row,) = script_returns(text, lua=True)
    assert len(row.expression) > 3200 and not row.diagnostic
    functions = script_functions(text, lua=True)
    value = functions.scalar("F()", 0, len(text), ())
    assert value.value == "FourCC('I001')"


def test_unclosed_return_is_retained_with_diagnostic() -> None:
    (row,) = script_returns("function F() return (1", lua=True)
    assert row.expression == "(1" and "未闭合" in row.diagnostic


@pytest.mark.parametrize("lua", [True, False])
def test_object_return_feeds_native_item_code_with_proof(lua: bool) -> None:
    script = _simple(lua)
    (row,) = trigger_acquisitions(script, lua=lua)
    assert row.item_code == "I001" and row.unit_codes == ("n001",)
    assert row.expression == "CreateItem(Id(),0,0)"
    assert any(
        "Id;" in proof and "return" in proof and "偏移" in proof
        for proof in row.value_proof
    )


@pytest.mark.parametrize("lua", [True, False])
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
def test_source_only_queries_resolve_getter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, lua: bool, command: str, query: str
) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")
    scripts = tmp_path / "脚本可读文本"
    scripts.mkdir()
    (scripts / ("war3map.lua" if lua else "war3map.j")).write_text(
        _simple(lua), encoding="utf-8"
    )
    output = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), command, query)
    ).render()
    assert "I001" in output and "Id()" in output
    assert "返回值证据" in output or command == "cmd"


@pytest.mark.parametrize("lua", [True, False])
def test_guide_reuses_getter_resolution(lua: bool) -> None:
    md = MapData(
        path="synthetic.w3x",
        name="返回值测试",
        scripts={"war3map.lua" if lua else "war3map.j": _simple(lua)},
    )
    output = format_guide_report(md, "drops")
    assert "I001[I001]" in output and "返回值证据" in output


def test_parameter_return_and_returned_argument_keep_both_proofs() -> None:
    script = _script(
        "function Name() return 'I001' end function Identity(x) return x end function Grant(id) CreateItem(id,0,0) end",
        "Grant(FourCC(Identity(Name())))",
    )
    (row,) = trigger_acquisitions(script, lua=True)
    assert row.item_code == "I001"
    graph = "\n".join(row.call_graph_lines)
    assert "返回值证据: Identity;" in graph and "返回值证据: Name;" in graph


def test_deep_getter_chain_uses_explicit_stack() -> None:
    depth = 1150
    helpers = (
        "\n".join(f"function F{i}() return F{i + 1}() end" for i in range(depth))
        + f"\nfunction F{depth}() return FourCC('I001') end"
    )
    (row,) = trigger_acquisitions(_script(helpers, "CreateItem(F0(),0,0)"), lua=True)
    assert row.item_code == "I001" and len(row.value_proof) == depth + 1


@pytest.mark.parametrize(
    "body",
    [
        "if choice then return FourCC('I001') end",
        "if choice then return FourCC('I001') else return FourCC('I002') end",
        "while choice do return FourCC('I001') end",
        "return Unknown()",
        "return Id()",
    ],
)
def test_uncertain_return_does_not_become_fixed_item(body: str) -> None:
    (row,) = trigger_acquisitions(
        _script(f"function Id() {body} end", "CreateItem(Id(),0,0)"), lua=True
    )
    assert row.item_code == "" and row.argument_evidence


def test_mutual_return_recursion_stays_diagnostic() -> None:
    (row,) = trigger_acquisitions(
        _script(
            "function A() return B() end function B() return A() end",
            "CreateItem(A(),0,0)",
        ),
        lua=True,
    )
    assert row.item_code == "" and "递归环" in row.argument_evidence


@pytest.mark.parametrize(
    "lua,literal", [(True, "'I001'"), (True, '"I001"'), (False, '"I001"')]
)
def test_plain_returned_string_does_not_become_object_code(
    lua: bool, literal: str
) -> None:
    script = _script(
        f"function Id() return {literal} end"
        if lua
        else f"function Id takes nothing returns string return {literal} endfunction",
        "CreateItem(Id(),0,0)" if lua else "call CreateItem(Id(),0,0)",
        lua=lua,
    )
    (row,) = trigger_acquisitions(script, lua=lua)
    assert row.item_code == ""


def test_getter_aliases_and_local_assignment_are_scope_aware() -> None:
    script = _script(
        "function Id() return FourCC('I001') end function Identity(x) local y=x; return y end",
        "local F=Id; local id=Identity(F()); CreateItem(id,0,0)",
    )
    (row,) = trigger_acquisitions(script, lua=True)
    assert row.item_code == "I001" and len(row.value_proof) == 2


def test_getter_reassignment_and_duplicate_definitions_stay_unknown() -> None:
    script = _script(
        "function Id() return FourCC('I001') end function Id() return FourCC('I002') end",
        "CreateItem(Id(),0,0)",
    )
    (row,) = trigger_acquisitions(script, lua=True)
    assert row.item_code == "" and "同名歧义" in row.argument_evidence


def test_scalar_context_uses_first_return_value_and_indexes_all_values() -> None:
    script = _script(
        "function Id() return FourCC('I001'),FourCC('I002') end", "CreateItem(Id(),0,0)"
    )
    (row,) = trigger_acquisitions(script, lua=True)
    assert row.item_code == "I001" and "I002" in row.value_proof[0]


def test_method_getter_binds_self_without_shifting_explicit_parameter() -> None:
    script = _script(
        "function Rewards:Identity(id) return id end",
        "CreateItem(Rewards:Identity(FourCC('I001')),0,0)",
    )
    (row,) = trigger_acquisitions(script, lua=True)
    assert row.item_code == "I001"


def test_getter_in_unit_selector_is_resolved_without_changing_source() -> None:
    script = _script(
        "function UnitId() return FourCC('n002') end function Id() return FourCC('I001') end",
        "if GetUnitTypeId(GetDyingUnit())==UnitId() then CreateItem(Id(),0,0) end",
    )
    (row,) = trigger_acquisitions(script, lua=True)
    assert row.item_code == "I001" and row.unit_codes == ("n001", "n002")
    assert any("==UnitId()" in condition for condition in row.conditions)
    assert any(
        "返回值/实参展开" in condition and "n002" in condition
        for condition in row.conditions
    )


def test_last_argument_expands_all_statically_known_return_values() -> None:
    script = _script(
        "function Ids() return FourCC('I001'),FourCC('I002') end function Grant(a,b) CreateItem(a,0,0); CreateItem(b,0,0) end",
        "Grant(Ids())",
    )
    rows = trigger_acquisitions(script, lua=True)
    assert {row.item_code for row in rows} == {"I001", "I002"}


def test_uninitialized_local_shadow_does_not_reuse_getter_parameter() -> None:
    script = _script(
        "function Id(x) do local x; return x end end",
        "CreateItem(Id(FourCC('I001')),0,0)",
    )
    (row,) = trigger_acquisitions(script, lua=True)
    assert row.item_code == ""


def test_getter_parameter_reassignment_does_not_reuse_caller_value() -> None:
    script = _script(
        "function Id(x) x=RuntimeValue(); return x end",
        "CreateItem(Id(FourCC('I001')),0,0)",
    )
    (row,) = trigger_acquisitions(script, lua=True)
    assert row.item_code == ""


def test_deep_nested_return_arguments_do_not_use_python_recursion() -> None:
    depth = 1050
    expression = "Id(" * depth + "FourCC('I001')" + ")" * depth
    (row,) = trigger_acquisitions(
        _script("function Id(x) return x end", f"CreateItem({expression},0,0)"),
        lua=True,
    )
    assert row.item_code == "I001" and row.graph is not None
    assert len(row.graph.edges) == depth


def test_getter_forwarding_preserves_parameter_context_across_functions() -> None:
    depth = 1050
    helpers = (
        "\n".join(f"function F{i}(x) return F{i + 1}(x) end" for i in range(depth))
        + f"\nfunction F{depth}(x) return x end"
    )
    (row,) = trigger_acquisitions(
        _script(helpers, "CreateItem(F0(FourCC('I001')),0,0)"), lua=True
    )
    assert row.item_code == "I001" and len(row.value_proof) == depth + 1


@pytest.mark.parametrize(
    "middle",
    [
        "Id=function() return FourCC('I002') end; CreateItem(Id(),0,0)",
        "do local Id=function() return FourCC('I002') end; CreateItem(Id(),0,0) end",
    ],
)
def test_value_cache_distinguishes_reassignments_and_block_visibility(
    middle: str,
) -> None:
    script = _script(
        "function Id() return FourCC('I001') end",
        "CreateItem(Id(),0,0); " + middle + "; CreateItem(Id(),0,0)",
    )
    rows = trigger_acquisitions(script, lua=True)
    expected = (
        ["I001", "I002", "I002"]
        if middle.startswith("Id=")
        else ["I001", "I002", "I001"]
    )
    assert [row.item_code for row in rows] == expected
