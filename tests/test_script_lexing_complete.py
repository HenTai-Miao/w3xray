"""Language-aware evidence must keep real calls and exclude quoted examples."""

from __future__ import annotations

import pytest

from gametool.map_data import MapData
from gametool.pack_query_placements import script_placements, script_rectangles
from gametool.save_call_context import clean_arg, extract_call_args
from gametool.script_lexing import literal_string_value, script_views
from gametool.script_string_index import build_script_string_index
from gametool.script_call_argument_index import build_script_call_argument_index
from gametool.script_call_catalog import build_script_call_catalog
from gametool.script_scan import scan_chat_commands, scan_object_refs
from gametool.script_tokens import script_code_text


def _map(script: str) -> MapData:
    md = MapData(path="synthetic.w3x", name="词法证据")
    md.scripts = {"war3map.lua": script}
    return md


def test_lua_catalog_excludes_long_and_single_quoted_call_examples() -> None:
    md = _map(
        "local example = [==[\nCreateItem(FourCC('I999'),1,2)\n]==]\n"
        "local quoted = 'CreateUnit(Player(0), FourCC(\"n999\"),1,2,0)'\n"
        "--[=[ UnitAddAbility(u,FourCC('A999')) ]=]\n"
        "CreateItem(FourCC('I001'),8 // 2,3)\n"
    )
    calls = build_script_call_catalog(md).calls
    assert [call.function for call in calls] == ["CreateItem", "FourCC"]
    assert calls[0].line == 6
    assert calls[0].object_codes == ("I001",)


def test_fourcc_has_no_fixed_prefix_window() -> None:
    script = "UnitAddAbility(u,FourCC(" + " " * 10000 + '"A001"))'
    assert '"A001"' in script_code_text(script)
    calls = build_script_call_catalog(_map(script)).calls
    assert next(
        call for call in calls if call.function == "UnitAddAbility"
    ).object_codes == ("A001",)


def test_lua_call_arguments_ignore_comment_punctuation_and_keep_long_strings() -> None:
    md = _map(
        "function real_setup()\n"
        "TriggerRegisterPlayerChatEvent(t,Player(0),\n"
        "  --[=[ misleading , ) ' text ]=]\n"
        "  [==[-load, (all)]==], true)\nend\n"
    )
    arguments = [
        row
        for row in build_script_call_argument_index(md).arguments
        if row.call == "TriggerRegisterPlayerChatEvent"
    ]
    assert len(arguments) == 4
    assert arguments[2].string_value == "-load, (all)"
    assert arguments[2].argument == "[==[-load, (all)]==]"


@pytest.mark.parametrize(
    ("script", "lua", "point"),
    [
        ("CreateItem('I001',1 // fake , )\n + 2,4)", False, (3, 4)),
        ("CreateItem(FourCC('I001'),8 // 2,3)", True, (4, 3)),
        ("CreateItem(FourCC('I001'),1 -- fake , )\n + 2,4)", True, (3, 4)),
        ("CreateItem(FourCC('I001'),1 --[==[ , ) ]==]\n + 2,4)", True, (3, 4)),
        ("CreateItem('I001',1--2,4)", False, (3, 4)),
    ],
)
def test_placements_use_real_language_and_comment_free_arguments(
    script: str, lua: bool, point: tuple[int, int]
) -> None:
    assert script_placements(script, lua=lua) == [("I001", *point, "item")]


def test_rectangles_allow_comments_between_numeric_tokens() -> None:
    script = "gg_rct_test=Rect(1,2,--[=[ , ) ]=]\n3,4)"
    assert script_rectangles(script, lua=True) == [("gg_rct_test", 1, 2, 3, 4)]


def test_chat_command_ignores_long_quoted_fake_registration() -> None:
    script = (
        'local fake = [[TriggerRegisterPlayerChatEvent(t,Player(0),"-fake",true)]]\n'
        'TriggerRegisterPlayerChatEvent(t,Player(0),"-real",true)\n'
    )
    assert [row.command for row in scan_chat_commands(script)] == ["-real"]


def test_deep_string_hash_context_does_not_depend_on_python_recursion() -> None:
    value = "StringHash(" * 3000 + '"hero-key"' + ")" * 3000
    assert clean_arg(value) == "hero-key"


def test_multiline_long_string_index_keeps_full_text_as_one_literal() -> None:
    text = "第一行\n" + "完整消息" * 3000 + '\nCreateItem(FourCC("I999"),0,0)'
    delimiter = "=" * 128
    md = _map(f"BJDebugMsg([{delimiter}[{text}]{delimiter}])\nBJDebugMsg('word')")
    rows = build_script_string_index(md).entries
    assert [row.value for row in rows] == [text, "word"]
    assert rows[0].line == 1 and rows[0].call == "BJDebugMsg"
    assert [row.function for row in build_script_call_catalog(md).calls] == [
        "BJDebugMsg",
        "BJDebugMsg",
    ]
    assert not any(row.object_codes for row in build_script_call_catalog(md).calls)


def test_lua_arguments_keep_tables_and_anonymous_function_blocks_together() -> None:
    call = (
        "Run({one=1,two={2,3}}, function() local a,b=1,2; "
        "for i=1,3 do if i>1 then a,b=b,a end end; return a,b end, 9)"
    )
    args = extract_call_args(call, len("Run("), lua=True)
    assert len(args) == 3
    assert args[0] == "{one=1,two={2,3}}"
    assert args[1].startswith("function()") and args[1].endswith("end")
    assert args[2] == "9"


def test_masked_arguments_keep_arity_and_cannot_create_object_codes_from_messages() -> (
    None
):
    script = "BJDebugMsg(\"message with 'I999' in it\")"
    views = script_views(script, lua=True)
    assert extract_call_args(views, len("BJDebugMsg("), mask_strings=True) == ("",)
    assert build_script_call_catalog(_map(script)).calls[0].object_codes == ()


@pytest.mark.parametrize(
    "value", ["'abc\\'", "'a' trailing", "[=[unclosed]", '"x" "y"']
)
def test_unclosed_or_multiple_literals_are_not_adopted_as_one_value(value: str) -> None:
    assert literal_string_value(value) is None


def test_long_bracket_fourcc_has_coordinates_and_real_object_evidence() -> None:
    script = "CreateItem(FourCC([=[I!ÿ1]=]),3.25,-2.5)"
    assert script_placements(script, lua=True) == [("I!ÿ1", 3.25, -2.5, "item")]
    calls = build_script_call_catalog(_map(script)).calls
    assert calls[0].object_codes == ("I!ÿ1",)


def test_lua_division_is_preserved_in_assignment_return_and_loop_evidence() -> None:
    from gametool.script_assignment_index import build_script_assignment_index
    from gametool.script_return_index import build_script_return_index
    from gametool.script_loop_index import build_script_loop_index

    md = _map(
        "function f()\nudg_Count=12 // 3\nwhile udg_Count // 2 > 0 do\nend\nreturn 9 // 2\nend"
    )
    assert build_script_assignment_index(md).assignments[0].value == "12 // 3"
    assert build_script_return_index(md).returns[0].expression == "9 // 2"
    assert build_script_loop_index(md).loops[0].expression == "udg_Count // 2 > 0"


def test_quoted_parenthesis_in_rawcode_cannot_end_a_native_call() -> None:
    assert scan_object_refs("call CreateItem('I)01',1,2)", lua=False)["物品"] == {
        "I)01"
    }
    assert scan_object_refs("CreateItem(FourCC('I)01'),8//2,2)", lua=True)["物品"] == {
        "I)01"
    }


def test_four_unicode_characters_cannot_masquerade_as_four_object_bytes() -> None:
    script = "CreateItem(FourCC('测试测试'),1,2)"
    assert script_placements(script, lua=True) == []
    assert not any(
        call.object_codes for call in build_script_call_catalog(_map(script)).calls
    )


def test_leading_jass_double_minus_is_an_expression() -> None:
    assert script_placements("CreateItem('I001',\n--1,2)", lua=False) == [
        ("I001", 1.0, 2.0, "item")
    ]


@pytest.mark.parametrize(
    "expression",
    [
        "FourCC('I001')+1",
        "FourCC('I001')+GetPlayerId(Player(0))",
        "FourCC('I001')+(FourCC('I999'))",
    ],
)
def test_fourcc_runtime_or_trailing_expression_is_not_a_literal_placement(
    expression: str,
) -> None:
    assert script_placements(f"CreateItem({expression},1,2)", lua=True) == []


def test_lua_save_calls_in_comments_do_not_enter_the_report() -> None:
    from gametool.save_analysis import build_save_report

    md = _map(
        '-- SaveInteger(h,1,StringHash("fake"),2)\nStoreInteger(c,"real","level",1)'
    )
    report = build_save_report(md)
    assert report.total == 1
    assert "level" in report.keys and "fake" not in report.keys


def test_raw_comment_only_call_has_no_arguments() -> None:
    assert extract_call_args("Run(--[=[ fake , ) ]=]\n)", len("Run("), lua=True) == ()
    assert extract_call_args(
        "Run('value')", len("Run("), lua=True, mask_strings=True
    ) == ("",)


def test_lua_trailing_string_in_condition_is_retained() -> None:
    from gametool.script_condition_branch_index import (
        build_script_condition_branch_index,
    )

    md = _map("function f()\nif udg_Name == '完整玩家名称' then\nend\nend")
    assert (
        build_script_condition_branch_index(md).branches[0].condition
        == "udg_Name == '完整玩家名称'"
    )
