"""Source helper chains retain literal contexts, call sites and uncertainty."""

from pathlib import Path

import pytest

from gametool import pack_query_cli as queries
from gametool.guide_report import format_guide_report
from gametool.map_data import MapData
from gametool.pack_query_options import PackQueryCliOptions
from gametool.script_function_graph import format_function_graph, script_functions
from gametool.script_trigger_acquisition import trigger_acquisitions
from gametool.script_trigger_bindings import script_trigger_bindings


def _script(helpers: str, action: str, *, lua: bool = True, condition: str = "") -> str:
    if lua:
        return (
            helpers + f"\nfunction Action() {action} end\nlocal t=CreateTrigger()\n"
            "TriggerRegisterAnyUnitEventBJ(t,EVENT_PLAYER_UNIT_DEATH)\n"
            "TriggerRegisterPlayerChatEvent(t,Player(0),'-test',true)\n"
            "TriggerAddCondition(t,Condition(function() return "
            + (condition or "GetUnitTypeId(GetDyingUnit())==FourCC('n001')")
            + " end))\nTriggerAddAction(t,Action)"
        )
    return (
        helpers
        + f"\nfunction Action takes nothing returns nothing {action} endfunction\n"
        "function Check takes nothing returns boolean return GetUnitTypeId(GetDyingUnit())=='n001' endfunction\n"
        "function Init takes nothing returns nothing set t=CreateTrigger()\n"
        "call TriggerRegisterAnyUnitEventBJ(t,EVENT_PLAYER_UNIT_DEATH)\n"
        'call TriggerRegisterPlayerChatEvent(t,Player(0),"-test",true)\n'
        "call TriggerAddCondition(t,Condition(function Check))\ncall TriggerAddAction(t,function Action)\nendfunction"
    )


def _simple(lua: bool) -> str:
    return _script(
        "function Grant(id) CreateItem(id,0,0) end"
        if lua
        else "function Grant takes integer id returns nothing call CreateItem(id,0,0) endfunction",
        "Grant(FourCC('I001'))" if lua else "call Grant('I001')",
        lua=lua,
    )


@pytest.mark.parametrize("lua", [True, False])
def test_helper_reward_keeps_source_call_and_parameter(lua: bool) -> None:
    script = _simple(lua)
    (row,) = trigger_acquisitions(script, lua=lua)
    assert row.item_code == "I001" and row.unit_codes == ("n001",)
    assert row.expression == "CreateItem(id,0,0)" and row.handler == "Action"
    assert row.graph is not None and len(row.graph.nodes) == 2
    assert "id" in row.argument_evidence and "I001" in row.argument_evidence
    assert script[row.offset :].startswith(row.expression)


@pytest.mark.parametrize("lua", [True, False])
@pytest.mark.parametrize(
    "command,query",
    [
        ("where", "I001"),
        ("drop", "I001"),
        ("drop", "n001"),
        ("where", "n001"),
        ("cmd", "-test"),
    ],
)
def test_source_only_query_reaches_helper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, lua: bool, command: str, query: str
) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")
    directory = tmp_path / "脚本可读文本"
    directory.mkdir()
    (directory / ("war3map.lua" if lua else "war3map.j")).write_text(
        _simple(lua), encoding="utf-8"
    )
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), command, query)
    )
    assert result.exit_code == 0
    output = result.render()
    assert (
        "静态调用图" in output and "I001" in output and "CreateItem(id,0,0)" in output
    )


@pytest.mark.parametrize("lua", [True, False])
def test_guide_drops_reuses_helper_evidence(lua: bool) -> None:
    md = MapData(
        path="synthetic.w3x",
        name="辅助调用",
        scripts={"war3map.lua" if lua else "war3map.j": _simple(lua)},
    )
    output = format_guide_report(md, "drops")
    assert "I001[I001]" in output and "n001[n001]" in output and "静态调用图" in output


def test_deep_chain_has_no_python_recursion_or_depth_cutoff() -> None:
    depth = 1100
    helpers = "\n".join(f"function F{i}(id) F{i + 1}(id) end" for i in range(depth))
    helpers += f"\nfunction F{depth}(id) CreateItem(id,0,0) end"
    (row,) = trigger_acquisitions(_script(helpers, "F0(FourCC('I001'))"), lua=True)
    assert row.item_code == "I001" and row.graph is not None
    assert len(row.graph.nodes) == depth + 2 and len(row.graph.edges) == depth + 1


def test_diamond_graph_shares_context_without_losing_invocation_sites() -> None:
    depth = 250
    helpers = "\n".join(
        f"function F{i}(id) F{i + 1}(id) F{i + 1}(id) end" for i in range(depth)
    )
    helpers += f"\nfunction F{depth}(id) CreateItem(id,0,0) end"
    script = _script(helpers, "F0(FourCC('I001'))")
    (row,) = trigger_acquisitions(script, lua=True)
    assert row.graph is not None and not row.graph.cyclic
    assert len(row.graph.nodes) == depth + 2 and len(row.graph.edges) == depth * 2 + 1
    assert len({edge.call.start for edge in row.graph.edges}) == depth * 2 + 1
    output = "\n".join(
        format_function_graph(
            row.graph, script_functions(script, lua=True), definitions=True
        )
    )
    assert output.count("函数原文:") == depth + 1


def test_mutual_recursion_terminates_by_context_identity_and_discloses_cycle() -> None:
    script = _script(
        "function A(id) B(id) end function B(id) A(id) CreateItem(id,0,0) end",
        "A(FourCC('I001'))",
    )
    (row,) = trigger_acquisitions(script, lua=True)
    assert row.item_code == "I001" and row.graph is not None and row.graph.cyclic
    assert len(row.graph.nodes) == 3 and len(row.graph.edges) == 3
    assert "递归环" in "\n".join(row.call_graph_lines)


def test_different_literal_arguments_and_selector_branches_do_not_mix() -> None:
    script = _script(
        "function Grant(id) CreateItem(id,0,0) end",
        "if GetUnitTypeId(GetDyingUnit())==FourCC('n002') then Grant(FourCC('I001')) else Grant(FourCC('I002')) end",
        condition="true",
    )
    rows = trigger_acquisitions(script, lua=True)
    by_code = {row.item_code: row for row in rows}
    assert by_code["I001"].unit_codes == ("n002",)
    assert by_code["I002"].unit_codes == ()
    assert len(rows) == 2 and rows[0].graph is rows[1].graph


@pytest.mark.parametrize(
    "assignment",
    [
        "local id=FourCC('I001'); id=RuntimeValue()",
        "local id=FourCC('I001'); if choice then id=FourCC('I002') end",
    ],
)
def test_reassignment_never_uses_stale_literal(assignment: str) -> None:
    rows = trigger_acquisitions(
        _script(
            "function Grant(id) CreateItem(id,0,0) end", assignment + "; Grant(id)"
        ),
        lua=True,
    )
    assert len(rows) == 1 and rows[0].item_code == ""
    assert "动态" in rows[0].argument_evidence or "未静态" in rows[0].argument_evidence


def test_fourcc_string_parameter_and_parentheses_are_static() -> None:
    script = _script(
        "function Grant(name) CreateItem((FourCC((name))),0,0) end", "Grant(('I001'))"
    )
    (row,) = trigger_acquisitions(script, lua=True)
    assert row.item_code == "I001"


def test_literal_aliases_and_parallel_assignments_keep_rhs_scope() -> None:
    script = _script(
        "function Grant(id) CreateItem(id,0,0) end",
        "local id=FourCC('I001'); local id,other=id,FourCC('I002'); Grant(id); Grant(other)",
    )
    assert {row.item_code for row in trigger_acquisitions(script, lua=True)} == {
        "I001",
        "I002",
    }


def test_block_local_does_not_hide_outer_literal_after_end() -> None:
    script = _script(
        "function Grant(id) CreateItem(id,0,0) end",
        "local id=FourCC('I001'); do local id=FourCC('I002'); Grant(id) end; Grant(id)",
    )
    assert {row.item_code for row in trigger_acquisitions(script, lua=True)} == {
        "I001",
        "I002",
    }


def test_function_alias_and_local_declaration_shadowing() -> None:
    script = _script(
        "function Grant(id) CreateItem(id,0,0) end",
        "local Give=Grant; do local Give=function(id) CreateItem(FourCC('I002'),0,0) end; Give(FourCC('I003')) end; Give(FourCC('I001'))",
    )
    assert {row.item_code for row in trigger_acquisitions(script, lua=True)} == {
        "I001",
        "I002",
    }


def test_shadowed_native_is_followed_as_source_function() -> None:
    script = _script(
        "local function CreateItem(id,x,y) BJDebugMsg('not native') end",
        "CreateItem(FourCC('I001'),0,0)",
    )
    assert trigger_acquisitions(script, lua=True) == ()


def test_condition_helper_stays_attached_to_trigger() -> None:
    script = _script(
        "function Check() return GetUnitTypeId(GetDyingUnit())==FourCC('n002') end function Grant(id) CreateItem(id,0,0) end",
        "Grant(FourCC('I001'))",
        condition="Check()",
    )
    (row,) = trigger_acquisitions(script, lua=True)
    assert row.unit_codes == ("n002",) and "条件处理器包含辅助调用" in row.diagnostic


def test_callback_alias_and_dynamic_callable_have_visible_provenance() -> None:
    script = "function Action() local f=RuntimeCallback(); f() end local alias=Action local t=CreateTrigger() TriggerAddAction(t,alias)"
    bindings = script_trigger_bindings(script, lua=True)
    callback = bindings.sites[-1].callback
    assert callback is not None and callback.functions[0].name == "Action"
    functions = script_functions(script, lua=True)
    graph = functions.graph(callback.functions[0])
    assert len(graph.edges) == 1 and graph.edges[0].target is None
    assert "动态回调表达式" in graph.edges[0].diagnostic


def test_qualified_and_method_calls_bind_explicit_arguments() -> None:
    script = _script(
        "function Rewards:Give(id) CreateItem(id,0,0) end",
        "Rewards:Give(FourCC('I001'))",
    )
    (row,) = trigger_acquisitions(script, lua=True)
    assert row.item_code == "I001" and row.graph is not None
    assert row.graph.nodes[1].arguments == (None, "FourCC('I001')")


def test_source_strings_and_unused_nested_functions_are_not_calls() -> None:
    script = _script(
        "function Grant(id) CreateItem(id,0,0) end",
        "local text='Grant(FourCC(\"I001\"))'; local function unused() Grant(FourCC('I002')) end; Grant(FourCC('I003'))",
    )
    assert [row.item_code for row in trigger_acquisitions(script, lua=True)] == ["I003"]


@pytest.mark.parametrize(
    "loop",
    ["for id=1,5 do Grant(id) end", "for _,id in ipairs(items) do Grant(id) end"],
)
def test_loop_parameters_do_not_reuse_outer_scalar(loop: str) -> None:
    script = _script(
        "function Grant(id) CreateItem(id,0,0) end",
        "local id=FourCC('I001'); " + loop + "; Grant(id)",
    )
    rows = trigger_acquisitions(script, lua=True)
    assert {row.item_code for row in rows} == {"", "I001"}


def test_loop_write_invalidates_previous_literal() -> None:
    script = _script(
        "function Grant(id) CreateItem(id,0,0) end",
        "local id=FourCC('I001'); while choice do id=FourCC('I002') end; Grant(id)",
    )
    (row,) = trigger_acquisitions(script, lua=True)
    assert row.item_code == ""


def test_condition_helper_and_action_branch_accept_literal_parameters() -> None:
    script = _script(
        "function Check(id) return GetUnitTypeId(GetDyingUnit())==id end function Grant(unit,id) if GetUnitTypeId(GetDyingUnit())==unit then CreateItem(id,0,0) end end",
        "Grant(FourCC('n003'),FourCC('I001'))",
        condition="Check(FourCC('n002'))",
    )
    (row,) = trigger_acquisitions(script, lua=True)
    assert row.unit_codes == ("n002", "n003") and row.item_code == "I001"
    assert any("字面量实参展开" in condition for condition in row.conditions)


def test_nested_callback_wrappers_and_parentheses_keep_exact_anonymous_span() -> None:
    script = "local t=CreateTrigger() TriggerAddCondition(t,Condition(Filter((function() return true end))))"
    callback = script_trigger_bindings(script, lua=True).sites[-1].callback
    assert callback is not None and len(callback.functions) == 1
    function = callback.functions[0]
    assert script[function.start : function.end] == "function() return true end"


def test_reached_helper_is_not_reported_again_as_an_unregistered_handler() -> None:
    script = _script(
        "function Grant(id) if GetUnitTypeId(GetDyingUnit())==FourCC('n002') then CreateItem(id,0,0) end end",
        "Grant(FourCC('I001'))",
    )
    (row,) = trigger_acquisitions(script, lua=True)
    assert row.item_code == "I001" and row.handler == "Action"


@pytest.mark.parametrize(
    "lua,literal", [(True, "'I001'"), (True, '"I001"'), (False, '"I001"')]
)
def test_plain_string_argument_is_not_an_integer_object_code(
    lua: bool, literal: str
) -> None:
    script = _script(
        "function Grant(id) CreateItem(id,0,0) end"
        if lua
        else "function Grant takes integer id returns nothing call CreateItem(id,0,0) endfunction",
        f"Grant({literal})" if lua else f"call Grant({literal})",
        lua=lua,
    )
    (row,) = trigger_acquisitions(script, lua=lua)
    assert row.item_code == "" and "未静态确定" in row.argument_evidence
