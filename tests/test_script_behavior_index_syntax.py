"""Unsupported callable syntax stays searchable without invented native identity."""

from __future__ import annotations

import pytest

from gametool.script_behavior_syntax import script_call_syntax_diagnostics
from gametool.script_scopes import script_structure


def _diagnostics(text: str, *, lua: bool = True):
    return script_call_syntax_diagnostics(
        text, lua=lua, known_calls=script_structure(text, lua=lua).calls
    )


def _calls(text: str, *, lua: bool = True):
    return tuple(row for row in _diagnostics(text, lua=lua) if row.callee)


@pytest.mark.parametrize(
    ("text", "callee", "arguments"),
    [
        ("table[key](a, b)", "table[key]", ("a", "b")),
        ("factory().foo(a)", "factory().foo", ("a",)),
        ("(f)(a)", "(f)", ("a",)),
        ("召唤(a)", "召唤", ("a",)),
        ("function召唤(a)", "function召唤", ("a",)),
        ("obj.召唤(a)", "obj.召唤", ("a",)),
        ("factory():method(a)", "factory():method", ("a",)),
        ("f 'hello'", "f", ("'hello'",)),
        ("f [==[hello\nworld]==]", "f", ("[==[hello\nworld]==]",)),
        ("f { a = 1, nested = { 2, 3 } }", "f", ("{ a = 1, nested = { 2, 3 } }",)),
        ("table[key]()", "table[key]", ()),
    ],
)
def test_complete_unsupported_calls_keep_exact_source(text, callee, arguments) -> None:
    calls = _calls(text)
    assert len(calls) == 1
    call = calls[0]
    assert call.code == "script.call.dynamic"
    assert call.raw == text
    assert call.callee == callee
    assert call.arguments == arguments
    assert call.complete
    assert (call.offset, call.end_offset) == (0, len(text))


def test_chained_dynamic_calls_remain_independent_sites() -> None:
    text = "factory().child[key](1).next 'text' (2)"
    calls = _calls(text)
    assert [row.callee for row in calls] == [
        "factory().child[key]",
        "factory().child[key](1).next",
        "factory().child[key](1).next 'text'",
    ]
    assert [row.arguments for row in calls] == [("1",), ("'text'",), ("2",)]
    assert all(text[row.offset : row.end_offset] == row.raw for row in calls)


def test_arguments_keep_comments_and_anonymous_function_commas() -> None:
    text = (
        "table[key](function(a, b) return a, b end, "
        "first -- complete comment\n + second, 'x,y', { k = { 1, 2 } })"
    )
    assert _calls(text)[0].arguments == (
        "function(a, b) return a, b end",
        "first -- complete comment\n + second",
        "'x,y'",
        "{ k = { 1, 2 } }",
    )


@pytest.mark.parametrize(
    "text",
    [
        "local x = (a + b)",
        "if (a) then local x = { a = 1 } end",
        "local x = { a = 'text', b = [[literal]] }",
        "function f(a, b) return a, b end",
        "function obj.f(a) return a end",
        "function obj:method(a) return a end",
        "local f = function(a) return a end",
        "function 召唤(a) return a end",
        "KnownCall(1, 'text', { key = 2 })",
        "local s = 'table[key](1)'; -- factory().method(2)\n--[=[f {1}]=]",
    ],
)
def test_non_calls_and_already_indexed_named_calls_are_not_repeated(text) -> None:
    assert not _diagnostics(text)


def test_sugar_inside_known_call_has_its_own_complete_record() -> None:
    text = "KnownCall(f 'x', table[key](2), { message = 'text' })"
    assert [row.raw for row in _calls(text)] == ["f 'x'", "table[key](2)"]


@pytest.mark.parametrize("text", ["f 'x'", "f {a=1}", "f [[text]]"])
def test_lua_parameter_sugar_is_not_assumed_in_jass(text) -> None:
    assert not _calls(text, lua=False)


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("local x = 'unclosed", "script.call.syntax.literal"),
        ("local x = [====[unclosed", "script.call.syntax.literal"),
        ("--[====[unclosed", "script.call.syntax.comment"),
        ("table[key](a", "script.call.syntax.incomplete"),
        ("f { a = 1", "script.call.syntax.incomplete"),
    ],
)
def test_unclosed_boundaries_remain_diagnostics_without_call_claims(text, code) -> None:
    rows = _diagnostics(text)
    assert any(row.code == code for row in rows)
    assert not any(row.callee for row in rows)
    assert all(text[row.offset : row.end_offset] == row.raw for row in rows)


def test_deep_grouping_and_all_dynamic_calls_have_no_input_ceiling() -> None:
    receiver = "(" * 1600 + "f" + ")" * 1600
    text = ";\n".join(f"{receiver}[{index}]({index})" for index in range(180))
    calls = _calls(text)
    assert len(calls) == 180
    assert [row.arguments for row in calls] == [(str(index),) for index in range(180)]
    assert all(text[row.offset : row.end_offset] == row.raw for row in calls)


def test_quoted_delimiters_comments_and_newlines_preserve_boundaries() -> None:
    text = "table[--not a close ]\r\n'key'](\"x)\", [==[a,b)]==], { [1] = '}' })"
    call = _calls(text)[0]
    assert call.raw == text
    assert call.arguments == ('"x)"', "[==[a,b)]==]", "{ [1] = '}' }")
