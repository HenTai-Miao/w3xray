"""Semantic script diagnostics retain lexical and control-flow evidence."""

from gametool.api import MapData
from gametool.diagnostics import build_script_diagnostics
from gametool.script_function_bindings import ScriptFunctionBindings
from gametool.script_sources import WCT_TEXT_NAME
import hashlib
import pytest


def _report(text: str, name: str = "war3map.j"):
    data = MapData(path="diagnostic.w3x", name="Diagnostic fixture")
    data.scripts = {name: text}
    return build_script_diagnostics(data)


def _codes(text: str, name: str = "war3map.j") -> set[str]:
    return set(_report(text, name).by_code)


def test_comment_and_string_api_words_are_not_calls() -> None:
    codes = _codes(
        "// GetLocalPlayer() DzGetMouseX() GetCameraTargetPositionX()\n"
        "function main takes nothing returns nothing\n"
        'call DisplayTextToPlayer(Player(0), 0, 0, "GetLocalPlayer() DzFoo()")\n'
        "endfunction\n"
    )
    assert not codes.intersection(
        {
            "script.get_local_player",
            "script.local_state.camera",
            "script.local_state.mouse",
            "script.dz_api",
        }
    )


def test_inner_endif_does_not_end_outer_local_branch() -> None:
    codes = _codes(
        "function main takes nothing returns nothing\n"
        "if GetLocalPlayer() == Player(0) then\n"
        "if true then\n"
        "call DoNothing()\n"
        "endif\n"
        "call CreateUnit(Player(0), 'hfoo', 0, 0, 0)\n"
        "endif\n"
        "endfunction\n"
    )
    assert "script.get_local_player.sync_mutation" in codes


def test_standalone_local_read_never_taints_next_function() -> None:
    codes = _codes(
        "function localRead takes nothing returns player\n"
        "return GetLocalPlayer()\n"
        "endfunction\n"
        "function independent takes nothing returns nothing\n"
        "call CreateUnit(Player(0), 'hfoo', 0, 0, 0)\n"
        "endfunction\n"
    )
    assert "script.get_local_player" in codes
    assert "script.get_local_player.sync_mutation" not in codes


@pytest.mark.parametrize("name", ["war3map.j", "war3map.lua"])
def test_case_and_unrelated_qualified_members_are_not_native(name: str) -> None:
    assert not _codes(
        "getlocalplayer()\nGETLOCALPLAYER()\nowner.GetLocalPlayer()\n"
        "owner.DzGetMouseX()\nowner.GetCameraTargetPositionX()\n",
        name,
    )


def test_lua_all_literal_forms_and_floor_division_preserve_language() -> None:
    text = (
        "-- GetLocalPlayer()\n--[========[ DzGetMouseX() ]========]\n"
        "local a = [==[GetLocalPlayer()]==]\n"
        "local b = 'GetCameraTargetPositionX()'\n"
        'local c = "DzGetMouseX()"\n'
        "local x = 5 // GetCameraTargetPositionX()\n"
    )
    report = _report(text, "war3map.lua")
    assert set(report.by_code) == {"script.local_state.camera"}
    call = report.by_code["script.local_state.camera"].calls[0]
    assert call.offset == text.rindex("GetCameraTargetPositionX")
    assert call.line == 6
    assert call.language == "Lua"


@pytest.mark.parametrize(
    "name, ending", [("war3map.j", "endif"), ("war3map.lua", "end")]
)
def test_else_and_elseif_keep_every_prior_local_predicate(
    name: str, ending: str
) -> None:
    report = _report(
        "if GetLocalPlayer() == Player(0) then\n"
        "CreateUnit()\n"
        "elseif true then\n"
        "CreateItem()\n"
        "elseif GetLocalPlayer() == Player(1) then\n"
        "SetUnitX()\n"
        "else\n"
        "SetUnitY()\n" + ending + "\nCreateUnit()\n",
        name,
    )
    calls = report.by_code["script.get_local_player.sync_mutation"].calls
    assert [item.callee for item in calls] == [
        "CreateUnit",
        "CreateItem",
        "SetUnitX",
        "SetUnitY",
    ]
    assert [[p.negated for p in item.predicates] for item in calls] == [
        [False],
        [True],
        [True, False],
        [True, True],
    ]


@pytest.mark.parametrize(
    "opener, closer",
    [
        ("while GetLocalPlayer() == Player(0) do", "end"),
        ("for i = 1, GetLocalPlayer() do", "end"),
    ],
)
def test_lua_loop_headers_own_body_only(opener: str, closer: str) -> None:
    calls = (
        _report(
            opener + "\nCreateUnit()\n" + closer + "\nCreateItem()\n", "war3map.lua"
        )
        .by_code["script.get_local_player.sync_mutation"]
        .calls
    )
    assert [item.callee for item in calls] == ["CreateUnit"]


def test_lua_callbacks_never_inherit_enclosing_execution_control() -> None:
    text = (
        "if GetLocalPlayer() then\n"
        "local callback = function() CreateUnit() end\n"
        "CreateItem()\nend\n"
        "function separate() CreateUnit() end\n"
    )
    calls = (
        _report(text, "war3map.lua")
        .by_code["script.get_local_player.sync_mutation"]
        .calls
    )
    assert [item.callee for item in calls] == ["CreateItem"]
    assert calls[0].owner == "<全局>"


@pytest.mark.parametrize("prefix", ["", "_G.", "_ENV."])
def test_standard_lua_environment_members_and_saved_aliases(prefix: str) -> None:
    text = (
        f"local who = {prefix}GetLocalPlayer\n"
        f"local create = {prefix}CreateUnit\n"
        "if who() then create() end\n"
    )
    report = _report(text, "war3map.lua")
    reads = report.by_code["script.get_local_player"].calls
    mutations = report.by_code["script.get_local_player.sync_mutation"].calls
    assert [(item.callee, item.canonical) for item in reads] == [
        ("who", "GetLocalPlayer")
    ]
    assert [(item.callee, item.canonical) for item in mutations] == [
        ("create", "CreateUnit")
    ]


@pytest.mark.parametrize(
    "replacement",
    [
        "GetLocalPlayer = function() return nil end",
        "function GetLocalPlayer() return nil end",
        "_G = {}",
        "_ENV = {}",
    ],
)
def test_saved_native_precedes_source_replacement(replacement: str) -> None:
    text = (
        "local who = GetLocalPlayer\nlocal create = CreateUnit\n"
        + replacement
        + "\nif who() then create() end\n"
    )
    report = _report(text, "war3map.lua")
    assert "script.get_local_player.sync_mutation" in report.by_code
    assert report.by_code["script.get_local_player"].calls[0].callee == "who"


@pytest.mark.parametrize(
    "prefix, call",
    [
        ("local _G = {}\n", "_G.GetLocalPlayer"),
        ("_G = {}\n", "_G.GetLocalPlayer"),
        ("local _ENV = {}\n", "GetLocalPlayer"),
        ("_ENV = {}\n", "_ENV.GetLocalPlayer"),
        ("local GetLocalPlayer\n", "GetLocalPlayer"),
    ],
)
def test_private_or_replaced_bindings_are_unknown_not_native(
    prefix: str, call: str
) -> None:
    report = _report(prefix + f"if {call}() then CreateUnit() end\n", "war3map.lua")
    assert "script.get_local_player.sync_mutation" not in report.by_code
    assert report.by_code["script.binding.unknown"].calls
    assert all(
        item.binding != "standard-global"
        for item in report.by_code["script.get_local_player"].calls
    )


def test_source_defined_function_is_not_api() -> None:
    text = "function GetLocalPlayer() return true end\nif GetLocalPlayer() then CreateUnit() end\n"
    assert not _codes(text, "war3map.lua")


def test_alias_binding_uncertainty_is_preserved() -> None:
    text = "local who = GetLocalPlayer\nif condition then who = dynamic end\nif who() then CreateUnit() end\n"
    report = _report(text, "war3map.lua")
    assert "script.get_local_player.sync_mutation" not in report.by_code
    assert any(
        item.callee == "who" for item in report.by_code["script.binding.unknown"].calls
    )


def test_source_and_character_offsets_keep_crlf_unicode_and_every_call() -> None:
    text = (
        "// 中文\r\n"
        + "if GetLocalPlayer() then\r\n"
        + "CreateUnit()\r\n" * 257
        + "endif\r\n"
    )
    report = _report(text, "scope/war3map.j")
    calls = report.by_code["script.get_local_player.sync_mutation"].calls
    assert len(calls) == 257
    assert [item.line for item in calls] == list(range(3, 260))
    for item in calls:
        assert item.source == "scope/war3map.j"
        assert text[item.offset : item.end_offset] == item.raw == "CreateUnit()"
        assert item.predicates[0].call_offsets == (text.index("GetLocalPlayer"),)
        assert len(item.source_fingerprint) == 64
        assert (
            item.location
            in report.by_code["script.get_local_player.sync_mutation"].detail
        )


def test_control_nesting_has_no_recursion_or_empirical_depth_limit() -> None:
    text = (
        "if GetLocalPlayer() then\n"
        + "if true then\n" * 1100
        + "CreateUnit()\n"
        + "endif\n" * 1101
    )
    assert (
        len(_report(text).by_code["script.get_local_player.sync_mutation"].calls) == 1
    )


def test_unknown_text_language_is_not_assumed_jass() -> None:
    report = _report("x = 5 // GetLocalPlayer()", "custom.txt")
    assert set(report.by_code) == {"script.language.unknown"}
    assert report.items[0].calls[0].language == "unknown"


def test_extra_builtin_resolver_default_is_unchanged() -> None:
    text = "local old = GetLocalPlayer\nfunction GetLocalPlayer() return nil end\nold()"
    plain = ScriptFunctionBindings(text, lua=True)
    extended = ScriptFunctionBindings(
        text, lua=True, additional_builtins={"GetLocalPlayer"}
    )
    position = text.rindex("old()")
    assert plain.resolve("old", position, None).functions
    assert extended.resolve("old", position, None).builtin == "GetLocalPlayer"


def test_foreign_script_definition_retains_binding_uncertainty() -> None:
    data = MapData(path="diagnostic.w3x", name="Diagnostic fixture")
    data.scripts = {
        "war3map.lua": "if GetLocalPlayer() then CreateUnit() end",
        "extra.lua": "function GetLocalPlayer() return nil end",
    }
    report = build_script_diagnostics(data)
    assert "script.get_local_player.sync_mutation" not in report.by_code
    assert "extra.lua" in report.by_code["script.binding.unknown"].detail


@pytest.mark.parametrize(
    "name,text",
    [
        (
            "war3map.lua",
            "repeat CreateUnit() until GetLocalPlayer() == Player(0); CreateItem()",
        ),
        (
            "war3map.lua",
            "repeat CreateUnit() until (\nGetLocalPlayer()\n)==Player(0)\nCreateItem()",
        ),
        (
            "war3map.j",
            "loop\nCreateUnit()\nexitwhen GetLocalPlayer() == Player(0)\nendloop\nCreateItem()",
        ),
    ],
)
def test_loop_exit_conditions_keep_iteration_dependency_and_scope(
    name: str, text: str
) -> None:
    report = _report(text, name)
    calls = report.by_code["script.get_local_player.sync_mutation"].calls
    assert [item.callee for item in calls] == ["CreateUnit"]
    assert calls[0].predicates[0].role == "loop-exit"
    assert "后续迭代" in report.by_code["script.get_local_player.sync_mutation"].detail


@pytest.mark.parametrize(
    "condition", ["true", '"GetLocalPlayer()"', "[=[GetLocalPlayer()]=]"]
)
def test_until_boundary_never_absorbs_following_statement(condition: str) -> None:
    text = f"repeat CreateUnit() until {condition} GetLocalPlayer()\nCreateItem()"
    assert "script.get_local_player.sync_mutation" not in _codes(text, "war3map.lua")


def test_nested_loop_exit_predicate_belongs_to_innermost_loop() -> None:
    text = (
        "loop\nCreateUnit()\nloop\nCreateItem()\n"
        "exitwhen GetLocalPlayer() == Player(0)\nendloop\n"
        "SetUnitX()\nexitwhen true\nendloop\n"
    )
    calls = _report(text).by_code["script.get_local_player.sync_mutation"].calls
    assert [item.callee for item in calls] == ["CreateItem"]


def test_unclosed_local_condition_is_uncertain() -> None:
    report = _report("if GetLocalPlayer() then\nCreateUnit()\n")
    assert "script.get_local_player.sync_mutation" not in report.by_code
    assert "script.local_mutation.unknown" in report.by_code


def test_unknown_prefix_match_does_not_claim_native_mutation() -> None:
    report = _report("if GetLocalPlayer() then\nSetUnitInvented()\nendif\n")
    assert "script.get_local_player.sync_mutation" not in report.by_code
    assert (
        report.by_code["script.local_mutation.unknown"].calls[0].canonical
        == "SetUnitInvented"
    )


def test_risk_api_shadowed_by_parameter_has_no_native_mutation() -> None:
    report = _report(
        "function own(GetLocalPlayer)\nif GetLocalPlayer() then CreateUnit() end\nend\n",
        "war3map.lua",
    )
    assert "script.get_local_player.sync_mutation" not in report.by_code
    assert report.by_code["script.local_mutation.unknown"].calls


def test_mutation_api_redefinition_is_analyzed_as_source_function() -> None:
    report = _report(
        "function CreateUnit() return nil end\nif GetLocalPlayer() then CreateUnit() end\n",
        "war3map.lua",
    )
    assert set(report.by_code) == {"script.get_local_player"}


def test_direct_get_local_read_does_not_create_control_state_in_same_function() -> None:
    text = "function main()\nlocal p = GetLocalPlayer()\nCreateUnit()\nend\n"
    assert set(_report(text, "war3map.lua").by_code) == {"script.get_local_player"}


def test_nested_predicate_callback_does_not_taint_parent_condition() -> None:
    text = "if Check(function() return GetLocalPlayer() end) then CreateUnit() end"
    assert set(_report(text, "war3map.lua").by_code) == {"script.get_local_player"}


def test_wct_inherits_lua_and_fingerprints_original_source() -> None:
    text = "// ===== 全局自定义脚本 =====\nif GetLocalPlayer() then CreateUnit() end"
    data = MapData(path="diagnostic.w3x", name="Diagnostic fixture")
    data.scripts = {"war3map.lua": "local a = 1", WCT_TEXT_NAME: text}
    report = build_script_diagnostics(data)
    call = report.by_code["script.get_local_player.sync_mutation"].calls[0]
    assert call.language == "Lua"
    assert call.source == WCT_TEXT_NAME
    assert call.line == 2
    assert call.offset == text.index("CreateUnit")
    assert call.source_fingerprint == hashlib.sha256(text.encode()).hexdigest()


def test_jass_qualified_spelling_is_not_assumed_native_syntax() -> None:
    report = _report("if _G.GetLocalPlayer() then CreateUnit() endif")
    assert "script.get_local_player.sync_mutation" not in report.by_code
    assert report.by_code["script.binding.unknown"].calls


def test_foreign_global_table_replacement_retains_uncertainty() -> None:
    data = MapData(path="diagnostic.w3x", name="Diagnostic fixture")
    data.scripts = {
        "war3map.lua": "if _G.GetLocalPlayer() then CreateUnit() end",
        "extra.lua": "_G = {}",
    }
    report = build_script_diagnostics(data)
    assert "script.get_local_player.sync_mutation" not in report.by_code
    assert "extra.lua" in report.by_code["script.binding.unknown"].detail


@pytest.mark.parametrize(
    "name,text",
    [
        (
            "war3map.j",
            "loop\nCreateUnit()\nexitwhen 玩家 == GetLocalPlayer()\nendloop\n",
        ),
        ("war3map.lua", "repeat\nCreateUnit()\nuntil 玩家 == GetLocalPlayer()\n"),
    ],
)
def test_unicode_loop_exit_identifier_preserves_complete_condition(
    name: str, text: str
) -> None:
    report = _report(text, name)
    calls = report.by_code["script.get_local_player.sync_mutation"].calls
    assert [item.callee for item in calls] == ["CreateUnit"]
    assert calls[0].predicates[0].raw.strip() == "玩家 == GetLocalPlayer()"
    assert calls[0].predicates[0].call_offsets == (text.index("GetLocalPlayer"),)


@pytest.mark.parametrize("literal", ["$FF", "0xFF", "1.5e+2"])
def test_loop_exit_numeric_token_does_not_cut_off_later_local_call(
    literal: str,
) -> None:
    text = f"loop\nCreateUnit()\nexitwhen {literal} == GetPlayerId(GetLocalPlayer())\nendloop\n"
    calls = _report(text).by_code["script.get_local_player.sync_mutation"].calls
    assert len(calls) == 1
    assert (
        calls[0].predicates[0].raw.strip()
        == f"{literal} == GetPlayerId(GetLocalPlayer())"
    )


@pytest.mark.parametrize(
    "text",
    [
        "",
        " \n\t",
        "call AllowedWct()",
        "AllowedWct()",
        'print("GetLocalPlayer() DzGetMouseX() GetCameraTargetPositionX()")',
        "print('GetLocalPlayer() DzFake()')",
        "local saved = GetLocalPlayer",
        "GetLocalPlayer",
        "CreateUnit()",
    ],
)
def test_unknown_language_without_relevant_call_has_no_warning(text: str) -> None:
    assert _report(text, WCT_TEXT_NAME).items == ()


@pytest.mark.parametrize(
    "text,seen_as",
    [
        ("GetLocalPlayer()", {"JASS", "Lua"}),
        ("value = 5 // GetLocalPlayer()", {"Lua"}),
        ("-- GetLocalPlayer()", {"JASS"}),
        ("// GetLocalPlayer()", {"Lua"}),
        ("local s = [==[GetLocalPlayer()]==]", {"JASS"}),
    ],
)
def test_unknown_language_preserves_actual_candidates_in_either_lexical_view(
    text: str, seen_as: set[str]
) -> None:
    report = _report(text, "custom.txt")
    assert set(report.by_code) == {"script.language.unknown"}
    calls = report.items[0].calls
    assert len(calls) == 1
    call = calls[0]
    assert call.language == "unknown"
    assert call.binding == "unknown"
    assert call.callee == "GetLocalPlayer"
    assert call.offset == text.index("GetLocalPlayer")
    assert call.raw == "GetLocalPlayer()"
    assert set(call.language_candidates) == seen_as


def test_unknown_language_retains_saved_risk_alias_as_unknown() -> None:
    text = "local read = GetLocalPlayer\nread()"
    calls = _report(text, "custom.txt").by_code["script.language.unknown"].calls
    assert any(
        item.callee == "read" and item.canonical == "GetLocalPlayer" for item in calls
    )
    assert all(item.binding == "unknown" for item in calls)


def test_unknown_language_floor_division_cannot_hide_foreign_potential_override() -> (
    None
):
    data = MapData(path="diagnostic.w3x", name="Diagnostic fixture")
    data.scripts = {
        "war3map.j": "if GetLocalPlayer() == Player(0) then CreateUnit() endif",
        "custom.txt": "local value = 4 // 2; GetLocalPlayer = replacement",
    }
    report = build_script_diagnostics(data)
    assert "script.get_local_player.sync_mutation" not in report.by_code
    detail = report.by_code["script.binding.unknown"].detail
    assert "custom.txt" in detail
    assert "语言未知" in detail
    assert "潜在覆盖" in detail


def test_unknown_language_shared_string_never_creates_foreign_override() -> None:
    data = MapData(path="diagnostic.w3x", name="Diagnostic fixture")
    data.scripts = {
        "war3map.j": "if GetLocalPlayer() == Player(0) then CreateUnit() endif",
        "custom.txt": 'local text = "GetLocalPlayer = replacement; GetLocalPlayer()"',
    }
    report = build_script_diagnostics(data)
    assert set(report.by_code) == {
        "script.get_local_player",
        "script.get_local_player.sync_mutation",
    }
    assert report.by_code["script.get_local_player"].scripts == ("war3map.j",)


def test_unknown_language_keeps_all_distinct_call_locations() -> None:
    text = "GetLocalPlayer()\n" * 263
    calls = _report(text, "custom.txt").by_code["script.language.unknown"].calls
    assert len(calls) == 263
    assert [item.line for item in calls] == list(range(1, 264))
    assert all(item.language_candidates == ("JASS", "Lua") for item in calls)
    assert len({item.offset for item in calls}) == 263


def test_unknown_language_distinct_raw_call_spans_are_not_merged() -> None:
    text = "GetLocalPlayer(-- )\n)"
    calls = _report(text, "custom.txt").by_code["script.language.unknown"].calls
    assert len(calls) == 2
    assert {item.raw for item in calls} == {"GetLocalPlayer(-- )", text}
    assert {item.language_candidates for item in calls} == {("JASS",), ("Lua",)}
    assert all(item.offset == 0 and item.binding == "unknown" for item in calls)


def test_unknown_language_retains_each_foreign_potential_assignment() -> None:
    data = MapData(path="diagnostic.w3x", name="Diagnostic fixture")
    data.scripts = {
        "war3map.j": "GetLocalPlayer()",
        "custom.txt": "GetLocalPlayer = first\nGetLocalPlayer = second",
    }
    detail = build_script_diagnostics(data).by_code["script.binding.unknown"].detail
    assert "custom.txt:1 / 偏移 0:22" in detail
    assert "custom.txt:2 / 偏移 23:46" in detail
    assert "GetLocalPlayer = first" in detail and "GetLocalPlayer = second" in detail
    assert "语言未知；JASS 词法下的潜在覆盖" in detail
    assert "语言未知；Lua 词法下的潜在覆盖" in detail
