"""WCT and exported text scripts retain their actual language and identity."""

from __future__ import annotations

from pathlib import Path

import pytest

from gametool.map_data import MapData
from gametool.pack_query_cli import execute_pack_query
from gametool.pack_query_options import PackQueryCliOptions
from gametool.placement_positions import script_position_groups
from gametool.script_call_catalog import build_script_call_catalog
from gametool.script_call_argument_index import build_script_call_argument_index
from gametool.script_function_index import build_script_function_index
from gametool.script_sources import (
    WCT_TEXT_NAME,
    analysis_script_sources,
    script_language,
)
from gametool.w3i import W3iInfo


def _lua_wct() -> MapData:
    md = MapData(path="synthetic.w3x", name="Lua 自定义代码")
    md.w3i = W3iInfo(script_type="Lua")
    md.scripts = {
        WCT_TEXT_NAME: (
            "// ===== 全局自定义脚本 =====\n"
            "function spawn()\n"
            "local fake=[=[CreateItem(FourCC('I999'),0,0)]=]\n"
            "CreateItem(FourCC('I001'),8 // 2,3)\n"
            "end\n"
        )
    }
    return md


def test_wct_context_keeps_source_name_and_line_offsets() -> None:
    md = _lua_wct()
    (entry,) = analysis_script_sources(md)
    assert entry.source == WCT_TEXT_NAME and entry.lua is True
    assert entry.text.startswith("-- =====")
    assert len(entry.text) == len(md.scripts[WCT_TEXT_NAME])
    assert md.scripts[WCT_TEXT_NAME].startswith("// =====")


@pytest.mark.parametrize(
    ("declared", "primaries", "expected"),
    [
        ("Lua", (), True),
        ("JASS", ("war3map.lua",), False),
        ("", ("war3map.lua",), True),
        ("", ("war3map.j",), False),
        ("", ("war3map.lua", "war3map.j"), None),
        ("", (), None),
    ],
)
def test_wct_language_uses_evidence_without_guessing(
    declared: str, primaries: tuple[str, ...], expected: bool | None
) -> None:
    assert (
        script_language(
            WCT_TEXT_NAME, available_sources=primaries, declared_script_type=declared
        )
        is expected
    )


def test_wct_catalog_arguments_functions_and_positions_share_lua_context() -> None:
    md = _lua_wct()
    calls = build_script_call_catalog(md).calls
    assert [call.function for call in calls] == ["CreateItem", "FourCC"]
    assert calls[0].line == 4 and calls[0].source == WCT_TEXT_NAME
    args = [
        arg
        for arg in build_script_call_argument_index(md).arguments
        if arg.call == "CreateItem"
    ]
    assert len(args) == 3 and args[1].argument == "8 // 2"
    assert all(arg.function == "spawn" for arg in args)
    assert script_position_groups(md, "item") == {"I001": ((4.0, 3.0),)}
    assert build_script_function_index(md).functions[0].end_line == 5


def test_pack_query_reads_wct_text_and_map_language(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gametool import pack_query_cli as queries

    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")
    scripts = tmp_path / "脚本可读文本"
    scripts.mkdir()
    (scripts / WCT_TEXT_NAME).write_text(
        _lua_wct().scripts[WCT_TEXT_NAME], encoding="utf-8"
    )
    (tmp_path / "地图信息.txt").write_text(
        "地图名称：测试\n脚本语言：Lua\n", encoding="utf-8"
    )
    result = execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "near", "4 3 1", near_kind="物品")
    )
    assert result.exit_code == 0
    entries = result.sections[0].entries
    assert len(entries) == 1 and entries[0]["code"] == "I001"
    assert entries[0]["x"] == 4 and entries[0]["y"] == 3


def test_mechanism_reports_do_not_adopt_names_from_comments_or_display_text() -> None:
    from gametool.script_mechanics import scan_script_features, scan_script_need_marks

    script = "local example=[=[ChooseRandomItemExBJ MeleeStartingHeroLimit]=]\n-- InitNeutralBuildings\nBJDebugMsg('ChooseRandomCreepBJ')"
    assert scan_script_features(script, lua=True) == ([], set())
    assert scan_script_need_marks(script, lua=True) == ()


def test_map_mechanism_report_keeps_lua_calls_after_division() -> None:
    from gametool.gui_script_mechanics_reports import build_script_mechanics_block
    from gametool.script_mechanics import map_script_mechanisms
    from gametool.knowledge_script_exports import format_script_index

    md = _lua_wct()
    md.scripts[WCT_TEXT_NAME] += "local n=8//2; ChooseRandomItemExBJ(0,n)\n"
    _features, _implicit, marks = map_script_mechanisms(md)
    assert any(mark.function == "ChooseRandomItemExBJ" for mark in marks)
    assert any("随机物品池" in line for line in build_script_mechanics_block(md).lines)
    assert "语言:Lua" in format_script_index(md)


def test_wct_expression_and_registration_indexes_keep_the_same_context() -> None:
    from gametool.script_assignment_index import build_script_assignment_index
    from gametool.script_local_index import build_script_local_index
    from gametool.script_return_index import build_script_return_index
    from gametool.script_loop_index import build_script_loop_index
    from gametool.script_condition_branch_index import (
        build_script_condition_branch_index,
    )
    from gametool.script_trigger_registration_index import (
        build_script_trigger_registration_index,
    )

    md = _lua_wct()
    md.scripts[WCT_TEXT_NAME] = (
        "// ===== 全局自定义脚本 =====\nfunction f()\n"
        "local count=8//2\nudg_Count=count\n"
        "if udg_Count//2>0 then\nend\n"
        "while udg_Count//2>0 do\nend\n"
        "TriggerRegisterPlayerChatEvent(t,Player(0),[=[-read]=],true)\n"
        "return udg_Count//2\nend"
    )
    assert build_script_local_index(md).locals[0].initial == "8//2"
    assert build_script_assignment_index(md).assignments[0].value == "count"
    assert (
        build_script_condition_branch_index(md).branches[0].condition
        == "udg_Count//2>0"
    )
    assert build_script_loop_index(md).loops[0].expression == "udg_Count//2>0"
    assert build_script_return_index(md).returns[0].expression == "udg_Count//2"
    registration = build_script_trigger_registration_index(md).registrations[0]
    assert registration.source == WCT_TEXT_NAME and registration.target == "-read"
    assert registration.function == "f"


def test_real_script_export_retains_wct_language_for_coordinate_queries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gametool import pack_query_cli as queries
    from gametool.knowledge_script_exports import write_readable_scripts
    from gametool.map_info import format_map_info

    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")
    folder = tmp_path / "脚本可读文本"
    folder.mkdir()
    md = _lua_wct()
    assert write_readable_scripts(md, str(folder)) == 1
    assert (folder / WCT_TEXT_NAME).is_file()
    (tmp_path / "地图信息.txt").write_text(format_map_info(md), encoding="utf-8")
    result = execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "near", "4 3 1", near_kind="物品")
    )
    assert result.exit_code == 0 and result.sections[0].entries[0]["code"] == "I001"
