"""Lua list builtins preserve source coverage and reject uncertain bindings."""

from pathlib import Path

import pytest

from gametool import pack_query_cli as queries
from gametool.guide_report import format_guide_report
from gametool.map_data import MapData
from gametool.pack_query_options import PackQueryCliOptions
from gametool.script_function_graph import script_functions
from gametool.script_lua_builtins import array_literal_parts, select_values
from gametool.script_trigger_acquisition import trigger_acquisitions
from gametool.script_value_models import StaticValue, StaticValues
from tests.test_script_multivalue_complete import _GRANT, _IDS, _codes, _script


@pytest.mark.parametrize(
    "expression,expected",
    [
        ("select(1,Ids())", ["I001", "I002", "I003"]),
        ("select(2,Ids())", ["I002", "I003", ""]),
        ("select(-1,Ids())", ["I003", "", ""]),
        ("select(-2,Ids())", ["I002", "I003", ""]),
        ("select(-3,Ids())", ["I001", "I002", "I003"]),
        ("select(4,Ids())", ["", "", ""]),
        ("select(9007199254740993,Ids())", ["", "", ""]),
        ("select(2.0,Ids())", ["I002", "I003", ""]),
        ("select(0x2,Ids())", ["I002", "I003", ""]),
        ('select("2",Ids())', ["I002", "I003", ""]),
        ("(select(2,Ids()))", ["I002", "", ""]),
        ("select(select('#',Ids()),Ids())", ["I003", "", ""]),
        ("table.unpack({Ids()})", ["I001", "I002", "I003"]),
        ("table.unpack({(Ids())})", ["I001", "", ""]),
        ("table.unpack({Ids(),FourCC('I004')})", ["I001", "I004", ""]),
        ("table.unpack({FourCC('I004'),Ids()})", ["I004", "I001", "I002"]),
        ("table.unpack({Ids()},2,3)", ["I002", "I003", ""]),
        ("table.unpack({Ids()},3,2)", ["", "", ""]),
        ("table.unpack({nil,FourCC('I002'),nil},1,3)", ["", "I002", ""]),
        ("table.unpack({FourCC('I001'),nil})", ["I001", "", ""]),
        ("table.unpack({})", ["", "", ""]),
        ("table.unpack({FourCC('I001');FourCC('I002');})", ["I001", "I002", ""]),
        (
            "table.unpack({FourCC('I001'), --[=[ , ; = } ]=]\n FourCC('I002')})",
            ["I001", "I002", ""],
        ),
        ("table.unpack(({Ids()}),nil,select('#',Ids()))", ["I001", "I002", "I003"]),
        ("table.unpack({select(2,Ids())})", ["I002", "I003", ""]),
        ("select(2,table.unpack({Ids()}))", ["I002", "I003", ""]),
    ],
)
def test_list_builtins_keep_lua_position_and_range_semantics(
    expression: str, expected: list[str]
) -> None:
    assert _codes(_IDS + _GRANT, f"Grant({expression})") == expected


@pytest.mark.parametrize("selector", ["'#'", "'#count'"])
@pytest.mark.parametrize(
    "args,count", [("", "0"), ("nil", "1"), ("nil,nil", "2"), ("1,nil,3", "3")]
)
def test_select_counts_nil_and_empty_lists(
    selector: str, args: str, count: str
) -> None:
    expression = f"select({selector}{',' + args if args else ''})"
    text = f"function F() return {expression} end"
    functions = script_functions(text, lua=True)
    owner = functions.structure.functions[0].start
    result = functions.scalar(expression, owner, len(text), ())
    assert result.value == count and result.kind == "number"


@pytest.mark.parametrize(
    "expression,note",
    [
        ("select(0,Ids())", "索引超出"),
        ("select(-4,Ids())", "索引超出"),
        ("select(1.5,Ids())", "整数"),
        ("select(1e1000000,Ids())", "整数"),
        ("select(false,Ids())", "整数"),
        ("select()", "整数"),
        ("table.unpack({nil,FourCC('I002')})", "空洞"),
        ("table.unpack({Unknown(),FourCC('I002')})", "未知值"),
        ("table.unpack({Ids()},0,3)", "源码已编码"),
        ("table.unpack({Ids()},1,9007199254740993)", "源码已编码"),
        ("table.unpack({Ids()},1.5,3)", "整数"),
        ("table.unpack({[2]=FourCC('I002')})", "显式索引"),
        ("table.unpack({item=FourCC('I002')})", "命名字段"),
        ("table.unpack(items)", "可变表"),
        ("table.unpack({Ids()}+{Ids()})", "数组以外"),
        ("table.unpack({Unknown()})", "尾部长度"),
    ],
)
def test_uncertain_or_invalid_lists_keep_diagnostics(
    expression: str, note: str
) -> None:
    rows = trigger_acquisitions(
        _script(_IDS + _GRANT, f"Grant({expression})"), lua=True
    )
    assert rows and all(not row.item_code for row in rows)
    assert note in "\n".join(rows[0].call_graph_lines)


def test_varargs_can_be_selected_and_unpacked_without_a_count_cap() -> None:
    helpers = (
        _IDS + _GRANT + "function Forward(...) return table.unpack({select(2,...)}) end"
    )
    assert _codes(helpers, "Grant(Forward(FourCC('I004'),Ids()))") == [
        "I001",
        "I002",
        "I003",
    ]


def test_unknown_tail_preserves_known_positive_suffix_but_not_negative_or_count() -> (
    None
):
    def number(raw: str) -> StaticValue:
        return StaticValue(raw, "number")

    tail = StaticValue(None, diagnostic="动态尾部")
    actual = StaticValues((number("2"), number("10"), number("20")), tail, True)
    selected = select_values(actual)
    assert selected.values == (number("20"),) and selected.tail == tail
    for selector in (number("-1"), StaticValue('"#"', "string")):
        result = select_values(StaticValues((selector, number("10")), tail, True))
        assert result.at(0).value is None and result.at(0).diagnostic


@pytest.mark.parametrize(
    "setup,expression,expected",
    [
        ("local pick=select;", "pick(2,Ids())", ["I002", "I003", ""]),
        ("local expand=table.unpack;", "expand({Ids()})", ["I001", "I002", "I003"]),
        (
            "local expand=table.unpack; table={};",
            "expand({Ids()})",
            ["I001", "I002", "I003"],
        ),
        (
            "local pick=select; select=function() return FourCC('I004') end;",
            "pick(2,Ids())",
            ["I002", "I003", ""],
        ),
        (
            "local select=function() return FourCC('I004') end;",
            "select(2,Ids())",
            ["I004", "", ""],
        ),
        (
            "local select=function() return FourCC('I004') end;",
            "_G.select(2,Ids())",
            ["I002", "I003", ""],
        ),
        (
            "local table={}; table.unpack=function() return FourCC('I004') end;",
            "table.unpack({Ids()})",
            ["I004", "", ""],
        ),
    ],
)
def test_builtin_aliases_capture_the_binding_at_assignment(
    setup: str, expression: str, expected: list[str]
) -> None:
    assert _codes(_IDS + _GRANT, f"{setup} Grant({expression})") == expected


@pytest.mark.parametrize(
    "setup,expression",
    [
        ("local table={};", "table.unpack({Ids()})"),
        ("table={};", "table.unpack({Ids()})"),
        (
            "table.unpack=function() return FourCC('I004') end; table={};",
            "table.unpack({Ids()})",
        ),
        ("local T={}; T.Get=function() return FourCC('I004') end; T={};", "T.Get()"),
    ],
)
def test_parent_replacement_never_reuses_old_member_or_standard_library(
    setup: str, expression: str
) -> None:
    rows = trigger_acquisitions(
        _script(_IDS + _GRANT, f"{setup} Grant({expression})"), lua=True
    )
    assert rows and all(not row.item_code for row in rows)
    assert "父表" in "\n".join(rows[0].call_graph_lines)


def test_array_splitter_keeps_function_bodies_and_opaque_strings_intact() -> None:
    parts, note = array_literal_parts(
        "{function(a,b) local x,y=1,2; return x,y end; [=[a,;=]}]=]; {1,2}}"
    )
    assert not note and parts is not None and len(parts) == 3
    assert parts[0].endswith("end") and parts[2] == "{1,2}"


def test_jass_select_is_an_external_function_without_lua_assumptions() -> None:
    text = "function F takes nothing returns integer\nreturn select(1, 'I001')\nendfunction"
    functions = script_functions(text, lua=False)
    owner = functions.structure.functions[0].start
    assert functions.scalar("select(1, 'I001')", owner, len(text), ()).value is None


def test_thousands_of_encoded_array_values_are_all_preserved() -> None:
    count = 1600
    expressions = ",".join(f"FourCC('I{i:03X}')" for i in range(count))
    text = "function F() end"
    functions = script_functions(text, lua=True)
    owner = functions.structure.functions[0].start
    result = functions.argument_values(
        (f"table.unpack({{{expressions}}})",), owner, len(text), ()
    )
    assert len(result.values) == count and result.tail is None
    assert result.values[-1].value == f"FourCC('I{count - 1:03X}')"


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
def test_queries_share_complete_builtin_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str, query: str
) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")
    scripts = tmp_path / "脚本可读文本"
    scripts.mkdir()
    text = _script(
        _IDS + _GRANT, "Grant(table.unpack({select(2,FourCC('I004'),Ids())}))"
    )
    (scripts / "war3map.lua").write_text(text, encoding="utf-8")
    output = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), command, query)
    ).render()
    assert "I002" in output and "I003" in output
    assert "table.unpack" in output and "select" in output


def test_guide_includes_the_same_builtin_results_and_proof() -> None:
    text = _script(
        _IDS + _GRANT, "Grant(table.unpack({select(2,FourCC('I004'),Ids())}))"
    )
    output = format_guide_report(
        MapData(path="synthetic.w3x", name="列表内建", scripts={"war3map.lua": text}),
        "drops",
    )
    assert all(code + "[" + code + "]" in output for code in ("I001", "I002", "I003"))
    assert "table.unpack" in output and "select" in output
