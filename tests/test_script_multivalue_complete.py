"""Lua list adjustment preserves every known return and uncertain tail."""

from pathlib import Path

import pytest

from gametool import pack_query_cli as queries
from gametool.guide_report import format_guide_report
from gametool.map_data import MapData
from gametool.pack_query_options import PackQueryCliOptions
from gametool.script_function_graph import script_functions
from gametool.script_trigger_acquisition import trigger_acquisitions

_IDS = "function Ids() return FourCC('I001'),FourCC('I002'),FourCC('I003') end\n"
_GRANT = "function Grant(a,b,c) CreateItem(a,0,0); CreateItem(b,0,0); CreateItem(c,0,0) end\n"


def _script(helpers: str, action: str) -> str:
    return (
        helpers
        + f"\nfunction Action() {action} end local t=CreateTrigger() TriggerRegisterAnyUnitEventBJ(t,EVENT_PLAYER_UNIT_DEATH) TriggerRegisterPlayerChatEvent(t,Player(0),'-test',true) TriggerAddCondition(t,Condition(function() return GetUnitTypeId(GetDyingUnit())==FourCC('n001') end)) TriggerAddAction(t,Action)"
    )


def _codes(helpers: str, action: str) -> list[str]:
    return [
        row.item_code
        for row in trigger_acquisitions(_script(helpers, action), lua=True)
    ]


@pytest.mark.parametrize(
    "expression,expected",
    [
        ("Grant(Ids())", ["I001", "I002", "I003"]),
        ("Grant((Ids()))", ["I001", "", ""]),
        ("Grant(Ids(),FourCC('I004'))", ["I001", "I004", ""]),
        ("Grant(FourCC('I004'),Ids())", ["I004", "I001", "I002"]),
        ("Grant(FourCC('I004'),(Ids()))", ["I004", "I001", ""]),
    ],
)
def test_argument_position_and_parentheses_adjust_lua_lists(
    expression: str, expected: list[str]
) -> None:
    assert _codes(_IDS + _GRANT, expression) == expected


@pytest.mark.parametrize(
    "rhs,expected",
    [
        ("Ids()", ["I001", "I002", "I003"]),
        ("(Ids())", ["I001", "", ""]),
        ("Ids(),FourCC('I004')", ["I001", "I004", ""]),
        ("FourCC('I004'),Ids()", ["I004", "I001", "I002"]),
    ],
)
def test_parallel_assignment_uses_complete_rhs_adjustment(
    rhs: str, expected: list[str]
) -> None:
    action = (
        f"local a,b,c={rhs}; CreateItem(a,0,0); CreateItem(b,0,0); CreateItem(c,0,0)"
    )
    assert _codes(_IDS, action) == expected


def test_parallel_swap_reads_every_rhs_before_assigning() -> None:
    assert _codes(
        _IDS, "local a,b=Ids(); a,b=b,a; CreateItem(a,0,0); CreateItem(b,0,0)"
    ) == ["I002", "I001"]


@pytest.mark.parametrize(
    "returned,expected",
    [
        ("Ids()", ["I001", "I002", "I003"]),
        ("(Ids())", ["I001", "", ""]),
        ("Ids(),FourCC('I004')", ["I001", "I004", ""]),
        ("FourCC('I004'),Ids()", ["I004", "I001", "I002"]),
    ],
)
def test_forwarded_return_list_uses_position_adjustment(
    returned: str, expected: list[str]
) -> None:
    assert (
        _codes(
            _IDS + _GRANT + f" function Forward() return {returned} end",
            "Grant(Forward())",
        )
        == expected
    )


@pytest.mark.parametrize(
    "returned,expected",
    [
        ("...", ["I001", "I002", "I003"]),
        ("(...)", ["I001", "", ""]),
        ("...,FourCC('I004')", ["I001", "I004", ""]),
        ("FourCC('I004'),...", ["I004", "I001", "I002"]),
    ],
)
def test_vararg_return_expands_only_in_final_position(
    returned: str, expected: list[str]
) -> None:
    assert (
        _codes(
            _IDS + _GRANT + f" function Forward(...) return {returned} end",
            "Grant(Forward(Ids()))",
        )
        == expected
    )


def test_named_head_and_variadic_tail_remain_separate() -> None:
    helpers = _IDS + _GRANT + " function Forward(head,...) return ... end"
    assert _codes(helpers, "Grant(Forward(FourCC('I004'),Ids()))") == [
        "I001",
        "I002",
        "I003",
    ]


def test_method_self_does_not_consume_a_variadic_item() -> None:
    helpers = _IDS + _GRANT + " function Rewards:Forward(head,...) return head,... end"
    assert _codes(helpers, "Grant(Rewards:Forward(FourCC('I004'),Ids()))") == [
        "I004",
        "I001",
        "I002",
    ]


def test_direct_vararg_native_uses_expanded_item_position() -> None:
    helpers = "function Args() return GetTriggerUnit(),FourCC('I002') end function Forward(...) UnitAddItemById(...) end"
    assert _codes(helpers, "Forward(Args())") == ["I002"]


def test_native_position_beyond_raw_argument_count_is_not_dropped() -> None:
    helpers = "function Args() return GetTriggerUnit(),FourCC('I002') end"
    (row,) = trigger_acquisitions(_script(helpers, "UnitAddItemById(Args())"), lua=True)
    assert row.item_code == "I002" and "展开后第2个" in row.argument_evidence
    assert "Args" in "\n".join(row.value_proof)


def test_vararg_parallel_assignment_preserves_all_slots() -> None:
    helpers = (
        _IDS
        + " function Give(...) local a,b,c=...; CreateItem(a,0,0); CreateItem(b,0,0); CreateItem(c,0,0) end"
    )
    assert _codes(helpers, "Give(Ids())") == ["I001", "I002", "I003"]


@pytest.mark.parametrize("body", ["return", ""])
def test_zero_return_has_zero_results_and_scalar_nil_padding(body: str) -> None:
    helpers = _GRANT + f" function Empty() {body} end"
    assert _codes(helpers, "Grant(Empty(),FourCC('I002'))") == ["", "I002", ""]
    functions = script_functions(helpers, lua=True)
    actual = functions.values.resolve_many("Empty()", 0, len(helpers), ())
    assert actual.values == () and actual.tail is None and actual.at(0).kind == "nil"


def test_unknown_last_return_preserves_prefix_and_unknown_tail() -> None:
    helpers = _GRANT
    assert _codes(helpers, "Grant(FourCC('I001'),Unknown())") == ["I001", "", ""]
    functions = script_functions(helpers, lua=True)
    actual = functions.argument_values(
        ("FourCC('I001')", "Unknown()"), 0, len(helpers), ()
    )
    assert actual.values[0].value == "FourCC('I001')" and actual.tail is not None
    assert actual.at(1000000).value is None and actual.at(1000000).diagnostic


def test_unknown_nonlast_return_never_shifts_following_values() -> None:
    assert _codes(_GRANT, "Grant(Unknown(),FourCC('I002'),FourCC('I003'))") == [
        "",
        "I002",
        "I003",
    ]


def test_unknown_vararg_tail_stays_unknown_in_a_forwarder() -> None:
    helpers = _GRANT + " function Forward(...) return ... end"
    assert _codes(helpers, "Grant(Forward(FourCC('I001'),Unknown()))") == [
        "I001",
        "",
        "",
    ]


def test_value_passed_as_object_code_is_not_reinterpreted_with_shadowed_fourcc() -> (
    None
):
    helpers = (
        "function Give(id) local FourCC=function() return 0 end; CreateItem(id,0,0) end"
    )
    assert _codes(helpers, "Give(FourCC('I001'))") == ["I001"]


def test_shadowed_fourcc_is_resolved_as_the_actual_source_function() -> None:
    helpers = "local function FourCC(x) return 1227894834 end"
    assert _codes(helpers, "CreateItem(FourCC('I001'),0,0)") == ["I002"]


def test_wide_return_list_and_parallel_lhs_have_no_count_ceiling() -> None:
    count = 1500
    ids = ",".join(f"FourCC('I{i:03X}')" for i in range(count))
    names = ",".join(f"v{i}" for i in range(count))
    actions = "; ".join(f"CreateItem(v{i},0,0)" for i in range(count))
    result = _codes(
        f"function Ids() return {ids} end", f"local {names}=Ids(); {actions}"
    )
    assert result == [f"I{i:03X}" for i in range(count)]


def test_deep_variadic_forwarding_uses_an_explicit_stack() -> None:
    depth = 1050
    helpers = (
        _IDS
        + _GRANT
        + "\n".join(
            f"function F{i}(...) return F{i + 1}(...) end" for i in range(depth)
        )
        + f"\nfunction F{depth}(...) return ... end"
    )
    assert _codes(helpers, "Grant(F0(Ids()))") == ["I001", "I002", "I003"]


def test_recursively_growing_varargs_keep_literal_prefix_and_diagnose_tail() -> None:
    helpers = "function Give(...) CreateItem(...); Give(FourCC('I002'),...) end"
    rows = trigger_acquisitions(_script(helpers, "Give(FourCC('I001'))"), lua=True)
    assert {row.item_code for row in rows} == {"I001", "I002"}
    assert "递归变长" in "\n".join(rows[0].call_graph_lines)
    assert rows[0].graph is not None and rows[0].graph.cyclic


def test_recursively_growing_return_is_diagnostic_without_a_depth_limit() -> None:
    helpers = _GRANT + " function Grow(...) return Grow(FourCC('I002'),...) end"
    rows = trigger_acquisitions(
        _script(helpers, "Grant(Grow(FourCC('I001')))"), lua=True
    )
    assert all(not row.item_code for row in rows)
    assert "递归" in "\n".join(rows[0].call_graph_lines)


def test_shrinking_varargs_keep_every_encoded_item_before_the_cycle() -> None:
    helpers = (
        _IDS
        + " function Give(first,...) CreateItem(first,0,0); if first~=nil then Give(...) end end"
    )
    result = _codes(helpers, "Give(Ids())")
    assert {code for code in result if code} == {"I001", "I002", "I003"}


@pytest.mark.parametrize(
    "command,query",
    [
        ("where", "I002"),
        ("drop", "I003"),
        ("where", "n001"),
        ("drop", "n001"),
        ("cmd", "-test"),
    ],
)
def test_queries_include_later_results_with_full_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str, query: str
) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")
    scripts = tmp_path / "脚本可读文本"
    scripts.mkdir()
    script = _script(
        _IDS + _GRANT + " function Forward(...) return ... end", "Grant(Forward(Ids()))"
    )
    (scripts / "war3map.lua").write_text(script, encoding="utf-8")
    output = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), command, query)
    ).render()
    assert "I002" in output and "I003" in output and "返回值证据" in output


def test_guide_keeps_all_returns_and_actual_native_calls() -> None:
    md = MapData(
        path="synthetic.w3x",
        name="多返回值",
        scripts={"war3map.lua": _script(_IDS + _GRANT, "Grant(Ids())")},
    )
    output = format_guide_report(md, "drops")
    assert all(code + "[" + code + "]" in output for code in ("I001", "I002", "I003"))
    assert output.count("原文: CreateItem(") == 3


@pytest.mark.parametrize(
    "parameters,expected",
    [
        ("nothing", ()),
        ("integer a, real b", ("a", "b")),
        ("integer\n a, string name", ("a", "name")),
    ],
)
def test_jass_parameter_list_never_includes_returns_keyword(
    parameters: str, expected: tuple[str, ...]
) -> None:
    text = f"function F takes {parameters} returns integer\nreturn 'I001'\nendfunction"
    functions = script_functions(text, lua=False)
    function = functions.structure.functions[0]
    assert functions.symbols.parameters[function.start] == expected
    assert all(name != "returns" for _owner, name in functions.symbols.locals)
