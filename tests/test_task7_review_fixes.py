"""Regressions for the Task 7 committed-diff review findings."""

from types import SimpleNamespace

from w3xtool.api import MapData, commands_from_map, recipes_from_map
from w3xtool.cheats import build_cheat_report
from w3xtool.compat import build_compat_report
from w3xtool.crash import build_crash_report
from w3xtool.diagnostics import build_script_diagnostics
from w3xtool.gui_script_mechanics_reports import build_script_mechanics_block
from w3xtool.object_id_usage import build_object_id_usage
from w3xtool.orders import build_order_report
from w3xtool.resources import build_resource_report
from w3xtool.save_analysis import build_save_report
from w3xtool.script_assignment_index import build_script_assignment_index
from w3xtool.script_call_argument_index import build_script_call_argument_index
from w3xtool.script_call_catalog import build_script_call_catalog
from w3xtool.script_condition_branch_index import build_script_condition_branch_index
from w3xtool.script_function_index import build_script_function_index
from w3xtool.script_global_index import build_script_global_index
from w3xtool.script_local_index import build_script_local_index
from w3xtool.script_loop_index import build_script_loop_index
from w3xtool.script_object_code_occurrence_index import (
    build_script_object_code_occurrence_index,
)
from w3xtool.script_return_index import build_script_return_index
from w3xtool.script_string_index import build_script_string_index
from w3xtool.script_trigger_registration_index import (
    build_script_trigger_registration_index,
)
from w3xtool.script_variable_usage_index import build_script_variable_usage_index
from w3xtool.ui_texts import build_ui_text_report

_ANALYSIS_SOURCES = {
    "war3map.j",
    "war3map.lua",
    "war3map.wct(custom).txt",
}


def _map_with_forbidden_sources(payload: str) -> MapData:
    return MapData(
        path="x.w3x",
        name="x",
        scripts={
            "war3map.j": "call AllowedJass()",
            "war3map.lua": "AllowedLua()",
            "war3map.wct(custom).txt": "call AllowedWct()",
            "war3map.wts": f"STRING 1\n{{\n{payload}\n}}\n",
            "war3map.wtg": payload,
            "war3map.wct": payload,
        },
    )


def _index_payload() -> str:
    return "\n".join((
        "globals",
        "integer udg_Forbidden = 'F001'",
        "endglobals",
        "function Forbidden takes nothing returns integer",
        "    local integer value = 1",
        "    set udg_Forbidden = value",
        "    if GetLocalPlayer() == Player(0) then",
        '        call SaveInteger(udg_hash, 1, 2, 3)',
        "    endif",
        "    loop",
        "        exitwhen true",
        "    endloop",
        '    call TriggerRegisterPlayerChatEvent(gg_trg_X, Player(0), "-x", true)',
        "    return 'F001'",
        "endfunction",
    ))


def test_every_script_index_excludes_wts_and_raw_binary_named_sources() -> None:
    # Given: every forbidden source contains indexable function-like JASS.
    md = _map_with_forbidden_sources(_index_payload())

    # When: all static script indexes are built.
    groups = (
        build_script_assignment_index(md).assignments,
        build_script_call_argument_index(md).arguments,
        build_script_condition_branch_index(md).branches,
        build_script_function_index(md).functions,
        build_script_global_index(md).globals,
        build_script_local_index(md).locals,
        build_script_loop_index(md).loops,
        build_script_object_code_occurrence_index(md).occurrences,
        build_script_return_index(md).returns,
        build_script_string_index(md).entries,
        build_script_trigger_registration_index(md).registrations,
        build_script_variable_usage_index(md).usages,
    )

    # Then: no index row can originate from WTS, WTG, or raw WCT.
    assert all(
        {item.source for item in group} <= _ANALYSIS_SOURCES
        for group in groups
    )


def test_call_save_and_object_analyzers_exclude_forbidden_sources() -> None:
    # Given: forbidden sources contain calls, save APIs, and object IDs.
    payload = "call ForbiddenCall('F001')\ncall SaveInteger(udg_hash, 1, 2, 3)"
    md = _map_with_forbidden_sources(payload)

    # When: representative investigation analyzers run.
    catalog = build_script_call_catalog(md)
    save_report = build_save_report(md)
    object_report = build_object_id_usage(md)

    # Then: only readable analysis sources contribute findings.
    assert {call.function for call in catalog.calls} == {
        "AllowedJass",
        "AllowedLua",
        "AllowedWct",
    }
    assert save_report.rows == ()
    assert object_report.entries == ()


def test_resource_diagnostic_gui_and_ui_reports_exclude_forbidden_sources() -> None:
    # Given: forbidden sources contain reportable resource, sync, mechanic, and TRIGSTR clues.
    payload = "\n".join((
        'call BlzLoadTOCFile("UI\\\\Forbidden.toc")',
        "call GetLocalPlayer()",
        "call ChooseRandomItemBJ(3)",
        "TRIGSTR_999",
    ))
    md = _map_with_forbidden_sources(payload)

    # When: representative reports are built.
    resources = build_resource_report(md)
    diagnostics = build_script_diagnostics(md)
    mechanics = build_script_mechanics_block(md)
    ui_texts = build_ui_text_report(md)

    # Then: WTS remains a string table, but none of the forbidden text is analyzed.
    assert resources.nodes == ()
    assert diagnostics.items == ()
    assert mechanics.lines == ()
    assert ui_texts.string_count == 1
    assert ui_texts.references == ()


def test_crash_cheat_order_and_compat_analyzers_exclude_forbidden_sources() -> None:
    # Given: forbidden sources contain known crash, cheat, order, and return-bug patterns.
    payload = "\n".join((
        'call InitGameCache("Forbidden.w3v")',
        'call BJDebugMsg("whosyourdaddy")',
        'call IssueImmediateOrder(u, "stop")',
        "function H2I takes handle h returns integer",
        "    return h",
        "endfunction",
    ))
    md = _map_with_forbidden_sources(payload)
    md.w3i = SimpleNamespace(version=25, script_type="JASS", large_map=False)

    # When / Then: forbidden sources cannot create analyzer findings.
    assert build_crash_report(md).items == ()
    assert build_cheat_report(md).items == ()
    assert build_order_report(md).uses == ()
    assert "script.return_bug" not in build_compat_report(md).by_code


def test_command_hints_do_not_cross_same_named_language_sources() -> None:
    # Given: JASS and Lua use the same trigger variable, but only JASS defines a hint.
    md = MapData(
        path="x.w3x",
        name="x",
        scripts={
            "war3map.j": "\n".join((
                'call TriggerRegisterPlayerChatEvent(gg_trg_Shared, Player(0), "-jass", true)',
                "function Trig_Shared_Actions takes nothing returns nothing",
                '    call BJDebugMsg("JASS hint")',
                "endfunction",
            )),
            "war3map.lua": (
                'TriggerRegisterPlayerChatEvent(gg_trg_Shared, Player(0), "-lua", true)'
            ),
        },
    )

    # When: commands are scanned from the map.
    hints = {command.command: command.hint for command in commands_from_map(md)}

    # Then: the Lua command cannot inherit the JASS action-function hint.
    assert hints == {"-jass": "JASS hint", "-lua": ""}


def test_command_hints_prefer_retained_byte_parsed_wts() -> None:
    # Given: byte parsing retained the mixed-encoding WTS value while the
    # published text contains a lossy fallback value.
    md = MapData(
        path="x.w3x",
        name="x",
        scripts={
            "war3map.j": "\n".join((
                'call TriggerRegisterPlayerChatEvent(gg_trg_X, Player(0), "-x", true)',
                "function Trig_X_Actions takes nothing returns nothing",
                '    call BJDebugMsg("TRIGSTR_001")',
                "endfunction",
            )),
            "war3map.wts": "STRING 1\n{\n损坏的重编码文本\n}\n",
        },
        ui_strings={1: "保留的混合编码提示"},
    )

    # When: command hints are resolved from the loaded map.
    commands = commands_from_map(md)

    # Then: the retained byte-oriented WTS table wins over reparsed UI text.
    assert [(item.command, item.hint) for item in commands] == [
        ("-x", "保留的混合编码提示"),
    ]


def test_partial_recipes_do_not_combine_across_sources() -> None:
    # Given: JASS removes ingredients while Lua only adds a result.
    md = MapData(
        path="x.w3x",
        name="x",
        scripts={
            "war3map.j": "\n".join((
                "function Partial takes nothing returns nothing",
                "    call RemoveItem(CreateItem('I001', 0, 0))",
                "    call RemoveItem(CreateItem('I002', 0, 0))",
            )),
            "war3map.lua": 'UnitAddItemById(u, FourCC("I003"))',
        },
    )

    # When / Then: source-local partials do not become a synthetic recipe.
    assert recipes_from_map(md) == []
