"""Source call queries retain every site without claiming runtime effects."""

import hashlib

import pytest

from gametool.script_behavior_catalog import (
    STANDARD_CALL_CATEGORIES,
    STANDARD_CALL_REFERENCES,
)
from gametool.script_behavior_index import build_script_behavior_index
from gametool.script_sources import AnalysisScriptSource


def _index(text: str, lua: bool | None = True):
    return build_script_behavior_index((AnalysisScriptSource("source", text, lua),))


def _calls(text: str, lua: bool | None = True):
    return _index(text, lua).calls


def test_every_site_zero_args_nested_calls_and_full_original_arguments() -> None:
    text = (
        "function main takes nothing returns nothing\r\n"
        "call CreateItem('I001', 1, 2)\r\n"
        "call CreateItem('I001', 1, 2)\r\n"
        "call SetHeroStr(GetTriggerUnit(), 20, true)\r\n"
        'call Unknown( "full\tcell\nwith\\"quote",  /*not a JASS comment*/ 8 )\r\n'
        "endfunction\r\n"
    )
    calls = _calls(text, False)
    assert [item.callee for item in calls] == [
        "CreateItem",
        "CreateItem",
        "SetHeroStr",
        "GetTriggerUnit",
        "Unknown",
    ]
    assert calls[0].offset != calls[1].offset
    assert calls[0].arguments == ("'I001'", "1", "2")
    assert calls[3].arguments == ()
    assert not calls[3].primary
    assert all(item.owner == "main" for item in calls)
    assert all(text[item.offset : item.end_offset] == item.raw for item in calls)
    assert calls[-1].arguments[0] == '"full\tcell\nwith\\"quote"'
    assert calls[-1].binding == "unknown"
    assert calls[0].source_fingerprint == hashlib.sha256(text.encode()).hexdigest()


def test_comments_strings_and_long_brackets_are_not_calls() -> None:
    text = (
        "-- CreateUnit()\n--[====[ SetHeroStr() ]====]\n"
        'local text = "CreateItem()"\n'
        "local literal = [==[SetUnitState()]==]\n"
        "local value = 8 // GetHeroLevel(hero)\n"
    )
    assert [item.callee for item in _calls(text)] == ["GetHeroLevel"]


def test_source_function_shadowing_retains_target_and_body_calls() -> None:
    text = (
        "function SetHeroStr(unit, value, permanent)\n"
        " SetUnitState(unit, UNIT_STATE_LIFE, value)\n"
        "end\nSetHeroStr(u, 20, true)\n"
    )
    calls = _calls(text)
    assert calls[0].binding == "standard-global"
    shadow = calls[1]
    assert shadow.binding == "source-function"
    assert shadow.canonical == shadow.category == ""
    assert len(shadow.targets) == 1
    assert shadow.targets[0].name == "SetHeroStr"
    assert shadow.targets[0].offset == 0


def test_alias_capture_before_later_replacement_keeps_original_binding() -> None:
    text = (
        "local original = SetHeroStr\n"
        "function SetHeroStr() end\n"
        "original(hero, 3, true)\nSetHeroStr(hero, 4, true)\n"
    )
    calls = _calls(text)
    assert calls[0].canonical == "SetHeroStr"
    assert calls[0].binding == "standard-global"
    assert calls[1].binding == "source-function"


@pytest.mark.parametrize(
    ("prefix", "callee", "binding"),
    [
        ("", "_G.SetHeroStr", "standard-global"),
        ("", "_ENV.SetHeroStr", "standard-global"),
        ("local _ENV = _G\n", "SetHeroStr", "standard-global"),
        ("local _ENV = {}\n", "SetHeroStr", "unknown"),
        ("local _ENV = {}\n", "_G.SetHeroStr", "unknown"),
        ("local _G = {}\n", "_G.SetHeroStr", "unknown"),
        ("_G = {}\n", "_G.SetHeroStr", "unknown"),
        ("", "owner.SetHeroStr", "unknown"),
        ("", "_G:SetHeroStr", "unknown"),
    ],
)
def test_global_environment_identity(prefix: str, callee: str, binding: str) -> None:
    call = _calls(prefix + callee + "(u, 1, true)")[0]
    assert call.binding == binding
    assert bool(call.category) == (binding == "standard-global")


def test_all_branch_guards_and_loop_exit_context_are_preserved() -> None:
    text = (
        "function main takes nothing returns nothing\n"
        "if GetPlayerState(Player(0), PLAYER_STATE_RESOURCE_GOLD) > 50 then\n"
        "loop\nexitwhen i > 8\nif ready then\n"
        "call SetHeroStr(hero, i, true)\nendif\nendloop\n"
        "elseif unlocked then\ncall SetHeroAgi(hero, 3, true)\n"
        "else\ncall SetHeroInt(hero, 4, true)\nendif\nendfunction\n"
    )
    by_name = {item.callee: item for item in _calls(text, False)}
    strength = by_name["SetHeroStr"]
    assert [item.kind for item in strength.controls] == ["if", "loop", "if"]
    assert strength.controls[1].predicates[0].role == "loop-exit"
    assert strength.controls[1].predicates[0].raw.strip() == "i > 8"
    agility = by_name["SetHeroAgi"]
    assert [p.negated for p in agility.controls[0].predicates] == [True, False]
    intelligence = by_name["SetHeroInt"]
    assert [p.negated for p in intelligence.controls[0].predicates] == [True, True]
    assert all(item.complete for item in strength.controls)


def test_callback_scope_does_not_inherit_enclosing_lexical_guard() -> None:
    text = (
        "if ready then\nTriggerAddAction(trigger, function()\n"
        "SetHeroStr(hero, 1, true)\nend)\nend\n"
    )
    calls = _calls(text)
    registration = next(item for item in calls if item.callee == "TriggerAddAction")
    mutation = next(item for item in calls if item.callee == "SetHeroStr")
    assert len(registration.controls) == 1
    assert mutation.controls == ()
    assert mutation.owner_offset != registration.owner_offset
    assert registration.arguments == (
        "trigger",
        "function()\nSetHeroStr(hero, 1, true)\nend",
    )


def test_lua_arguments_keep_comments_tables_and_callback_commas() -> None:
    text = (
        "custom( -- first\n 'a,b', {one=1,two={2,3}}, "
        "function(x,y) return x,y end, value -- last\n)"
    )
    call = _calls(text)[0]
    assert call.arguments == (
        "-- first\n 'a,b'",
        "{one=1,two={2,3}}",
        "function(x,y) return x,y end",
        "value -- last",
    )


def test_uncertain_aliases_keep_raw_and_global_diagnostics() -> None:
    text = (
        "local action = SetHeroStr\n"
        "if flag then action = SetHeroInt end\n"
        "action(hero, 1, true)\n"
    )
    index = _index(text)
    assert index.calls[0].binding == "unknown"
    assert index.calls[0].canonical == index.calls[0].category == ""
    assert "分支" in "\n".join(index.calls[0].diagnostics)
    assert index.diagnostics[0].raw == "action(hero, 1, true)"


def test_unknown_language_retains_both_lexical_candidates_as_unknown() -> None:
    text = "SetHeroStr(hero, 1, true)\nlocal value = 8 // SetHeroInt(hero, 2, true)\n"
    index = _index(text, None)
    assert {item.callee for item in index.calls} == {"SetHeroStr", "SetHeroInt"}
    first = next(item for item in index.calls if item.callee == "SetHeroStr")
    assert first.language_candidates == ("JASS", "Lua")
    assert all(item.binding == "unknown" and not item.canonical for item in index.calls)
    assert all(item.language == "unknown" and not item.controls for item in index.calls)
    assert any(
        item.code == "script.language.unknown" and item.raw == text
        for item in index.diagnostics
    )


def test_unknown_language_without_named_calls_keeps_full_source_diagnostic() -> None:
    text = 'local note = "not executable"'
    index = _index(text, None)
    assert index.calls == ()
    assert any(item.raw == text for item in index.diagnostics)


def test_cross_source_global_override_prevents_native_claim() -> None:
    index = build_script_behavior_index(
        (
            AnalysisScriptSource("first.lua", "SetHeroStr(u, 1, true)", True),
            AnalysisScriptSource("second.lua", "function SetHeroStr() end", True),
        )
    )
    assert len(index.calls) == 1
    assert index.calls[0].binding == "unknown"
    assert "second.lua" in "\n".join(index.calls[0].diagnostics)
    assert "function SetHeroStr() end" in "\n".join(index.calls[0].diagnostics)


def test_cross_source_local_shadow_does_not_replace_another_source_global() -> None:
    index = build_script_behavior_index(
        (
            AnalysisScriptSource("first.lua", "SetHeroStr(u, 1, true)", True),
            AnalysisScriptSource("second.lua", "local SetHeroStr = custom", True),
        )
    )
    assert index.calls[0].binding == "standard-global"


def test_cross_source_global_function_alias_retains_unknown_target_order() -> None:
    index = build_script_behavior_index(
        (
            AnalysisScriptSource(
                "first.lua", "function task() end\nlocal alias = task\nalias()", True
            ),
            AnalysisScriptSource("second.lua", "function task() end", True),
        )
    )
    call = index.calls[0]
    assert call.callee == "alias"
    assert call.binding == "unknown"
    assert call.targets[0].name == "task"
    assert "second.lua" in "\n".join(call.diagnostics)


def test_cross_source_parent_table_replacement_retains_binding_uncertainty() -> None:
    index = build_script_behavior_index(
        (
            AnalysisScriptSource(
                "first.lua", "function handlers.run() end\nhandlers.run()", True
            ),
            AnalysisScriptSource("second.lua", "handlers = replacement", True),
        )
    )
    assert index.calls[0].binding == "unknown"
    assert "handlers = replacement" in "\n".join(index.calls[0].diagnostics)


def test_independent_sources_and_identical_sites_never_merge() -> None:
    text = "SetHeroStr(u, 1, true)"
    index = build_script_behavior_index(
        (
            AnalysisScriptSource("first.lua", text, True),
            AnalysisScriptSource("second.lua", text, True),
            AnalysisScriptSource("first.lua", text, True),
        )
    )
    assert [item.source for item in index.calls] == [
        "first.lua",
        "second.lua",
        "first.lua",
    ]


def test_dynamic_calls_are_searchable_records_with_full_expressions() -> None:
    text = (
        "if ready then\ntable[key]('a,b', {x=1,y=2})\n"
        "factory().SetHeroStr(hero, 3, true)\n"
        "say [==[complete\ntext]==]\n"
        "build {hero, 3}\nend\n"
    )
    index = _index(text)
    dynamic = [
        item
        for item in index.calls
        if item.callee in {"table[key]", "factory().SetHeroStr", "say", "build"}
    ]
    assert len(dynamic) == 4
    assert all(item.binding == "unknown" and not item.category for item in dynamic)
    assert all(
        item.controls and item.controls[0].condition == "ready" for item in dynamic
    )
    assert dynamic[0].arguments == ("'a,b'", "{x=1,y=2}")
    assert dynamic[2].arguments == ("[==[complete\ntext]==]",)
    assert all(text[item.offset : item.end_offset] == item.raw for item in dynamic)


def test_incomplete_functions_calls_and_literals_are_not_silent_empty_results() -> None:
    text = "function broken()\nSetHeroStr(hero, 1, true)\nunfinished(1, 2\n"
    index = _index(text)
    assert index.calls[0].binding == "unknown"
    assert any(item.code == "script.function.incomplete" for item in index.diagnostics)
    assert any("unfinished" in item.raw for item in index.diagnostics)
    literal = _index("local text = [====[ never closed")
    assert literal.calls == ()
    assert literal.diagnostics


def test_complete_no_call_sources_are_empty_without_invented_runtime_claims() -> None:
    assert _index("-- comments only\n").calls == ()
    assert _index("local n = 1\n").calls == ()
    assert build_script_behavior_index(()).diagnostics == ()


def test_unbounded_alias_chain_and_every_guard_after_old_count_boundaries() -> None:
    count = 1200
    text = (
        "local alias0 = SetHeroStr\n"
        + "".join(f"local alias{i} = alias{i - 1}\n" for i in range(1, count))
        + f"alias{count - 1}(hero, 3, true)\n"
    )
    assert _calls(text)[0].canonical == "SetHeroStr"
    text = (
        "".join("if ready then\n" for _ in range(count))
        + "SetHeroStr(u, 1, true)\n"
        + "end\n" * count
    )
    call = next(item for item in _calls(text) if item.callee == "SetHeroStr")
    assert len(call.controls) == count
    assert all(item.complete for item in call.controls)


def test_every_call_beyond_previous_empirical_limits_is_kept() -> None:
    count = 2501
    text = "\n".join(f"SetHeroStr(hero, {i}, true)" for i in range(count))
    calls = _calls(text)
    assert len(calls) == count
    assert calls[-1].arguments[1] == "2500"
    assert len({item.offset for item in calls}) == count


def test_reference_categories_are_exact_and_preserve_wrapper_identity() -> None:
    assert STANDARD_CALL_REFERENCES["SetPlayerState"][1] == "native"
    assert STANDARD_CALL_REFERENCES["SetPlayerStateBJ"][1] == "function"
    assert STANDARD_CALL_CATEGORIES["SetPlayerState"] == "玩家状态/资源"
    assert STANDARD_CALL_CATEGORIES["CreateDestructable"] == "可破坏物"
    assert STANDARD_CALL_CATEGORIES["SetWidgetLife"] == "实体生命"
    calls = _calls("SetPlayerStateFake(p, x, 1)\nSetHeroStrange(u, 2)")
    assert all(item.binding == "unknown" and not item.category for item in calls)


def test_jass_qualified_names_do_not_become_native_calls() -> None:
    call = _calls("call _G.SetHeroStr(hero, 1, true)", False)[0]
    assert call.binding == "unknown"
    assert call.canonical == call.category == ""


def test_dynamic_receiver_chain_keeps_each_site_and_outer_primary() -> None:
    calls = _calls("factory().member(1).next 'text'")
    assert len(calls) == 3
    assert len({(item.offset, item.end_offset, item.callee) for item in calls}) == 3
    assert sum(item.primary for item in calls) == 1
    assert calls[-1].primary
    assert calls[-1].raw == "factory().member(1).next 'text'"


def test_unknown_source_order_stays_between_other_supplied_sources() -> None:
    index = build_script_behavior_index(
        (
            AnalysisScriptSource("first.lua", "SetHeroStr(u, 1, true)", True),
            AnalysisScriptSource("unknown.txt", "SetHeroAgi(u, 2, true)", None),
            AnalysisScriptSource("last.lua", "SetHeroInt(u, 3, true)", True),
        )
    )
    assert [item.source for item in index.calls] == [
        "first.lua",
        "unknown.txt",
        "last.lua",
    ]


def test_incomplete_control_without_calls_retains_source_diagnostic() -> None:
    index = _index("if flag then\nlocal value = 1\n")
    assert index.calls == ()
    assert any(item.code == "script.control.incomplete" for item in index.diagnostics)


def test_missing_argument_is_not_a_complete_confirmed_call() -> None:
    call = _calls("SetHeroStr(hero, , true)")[0]
    assert call.arguments == ("hero", "", "true")
    assert not call.complete
    assert call.binding == "unknown"


def test_lua_only_function_is_not_assumed_in_jass() -> None:
    calls = _calls('call select(1, 2)\ncall FourCC("hfoo")', False)
    assert all(item.binding == "unknown" and not item.category for item in calls)
