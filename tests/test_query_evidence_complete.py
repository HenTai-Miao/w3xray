"""All query evidence survives name collisions and explicit record limits."""

from __future__ import annotations

import csv
import os
from pathlib import Path

import pytest

from gametool import pack_query_cli as queries
from gametool.item_relation_exports import ACQUISITION_REPORT_HEADER
from gametool.pack_query_options import PackQueryCliOptions


def _rows(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        csv.writer(stream, delimiter="\t").writerows(rows)


def _objects(pack: Path, category: str, entries: list[tuple[str, str, str]]) -> None:
    _rows(
        pack / "对象ID" / f"{category}.tsv",
        [
            ["分类", "ID", "数值", "基础ID", "名称", "自定义", "说明"],
            *[
                [category, code, "1", code, name, "是", desc]
                for code, name, desc in entries
            ],
        ],
    )


@pytest.fixture
def pack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")
    return tmp_path


def _acquisition_pack(pack: Path, kind: str = "商店出售") -> None:
    _objects(pack, "物品", [(f"I{i:03}", "同名装备", "") for i in range(1, 3)])
    _objects(pack, "单位", [(f"n{i:03}", "同名怪物", "") for i in range(1, 3)])
    row = [""] * len(ACQUISITION_REPORT_HEADER)
    row[2:8] = [kind, "I001", "同名装备", "单位", "n001", "同名怪物"]
    _rows(pack / "掉落与获取关系.tsv", [list(ACQUISITION_REPORT_HEADER), row])
    scripts = pack / "脚本可读文本"
    scripts.mkdir()
    (scripts / "war3map.j").write_text(
        "\n".join(
            f"function Unit{i}Actions takes nothing returns nothing\n"
            f"if GetUnitTypeId(GetDyingUnit()) == 'n{i:03}' then\n"
            f"call CreateItem('I{i:03}', 0, 0)\nendif\nendfunction\n"
            for i in range(1, 3)
        ),
        encoding="utf-8",
    )


@pytest.mark.parametrize("command", ["where", "drop"])
@pytest.mark.parametrize("kind", ["商店出售", "单位掉落"])
def test_relations_never_hide_another_matching_items_script_evidence(
    pack: Path, command: str, kind: str
) -> None:
    _acquisition_pack(pack, kind)
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(pack), command, "同名装备")
    )
    assert result.exit_code == 0
    text = result.render()
    assert "I001" in text and "I002" in text
    assert "CreateItem('I002', 0, 0)" in text or "CreateItem('I002',0,0)" in text
    assert "Unit2Actions" in text
    assert "关系表无此掉落记录" not in text


@pytest.mark.parametrize("command", ["where", "drop"])
def test_source_side_relations_do_not_hide_other_same_named_units(
    pack: Path, command: str
) -> None:
    _acquisition_pack(pack, "单位掉落")
    text = queries.execute_pack_query(
        PackQueryCliOptions(str(pack), command, "同名怪物")
    ).render()
    assert "n001" in text and "n002" in text
    assert "Unit2Actions" in text and "I002" in text


@pytest.mark.parametrize("command", ["where", "drop"])
@pytest.mark.parametrize("limit", [0, 1, 2, 3])
def test_acquisition_limits_keep_whole_script_evidence_and_exact_remainder(
    pack: Path, command: str, limit: int
) -> None:
    _acquisition_pack(pack)
    text = queries.execute_pack_query(
        PackQueryCliOptions(str(pack), command, "同名装备", limit=limit)
    ).render()
    assert "Unit1Actions" in text
    # where has two script coordinates plus one relation; drop has one relation
    # and the other item's script-only evidence record.
    total = 3 if command == "where" else 2
    if limit == 1:
        assert "Unit2Actions" not in text
    else:
        assert "Unit2Actions" in text
    if limit and limit < total:
        assert f"其余 {total - limit} 条未显示" in text
    else:
        assert "已达 --limit" not in text


@pytest.mark.parametrize("limit", [0, 1, 3])
def test_where_tooltip_fallback_counts_all_hints_before_limiting(
    pack: Path, limit: int
) -> None:
    _objects(
        pack,
        "物品",
        [("I000", "目标装备", "")]
        + [
            (f"I{i:03}", f"线索{i}", "目标装备掉落来源：" + "完整证据" * 1000)
            for i in range(1, 4)
        ],
    )
    text = queries.execute_pack_query(
        PackQueryCliOptions(str(pack), "where", "I000", limit=limit)
    ).render()
    assert "文案级" in text and "完整证据" * 1000 in text
    if limit == 1:
        assert "其余 2 条未显示" in text and "线索3" not in text
    else:
        assert "线索3" in text and "已达 --limit" not in text


def _references(pack: Path) -> None:
    _rows(
        pack / "脚本对象码出现索引.tsv",
        [
            [
                "war3map.j",
                "1",
                "GiveOne",
                "I001",
                "",
                "物品",
                "同名弓",
                "",
                "",
                "CreateItem",
                "call CreateItem('I001',0,0)",
            ],
            [
                "war3map.wct(自定义代码).txt",
                "2",
                "GiveTwo",
                "I001",
                "",
                "物品",
                "同名弓",
                "",
                "",
                "CreateItem",
                "call CreateItem('I001',0,0)",
            ],
            [
                "war3map.j",
                "3",
                "ConsumeOther",
                "I002",
                "",
                "物品",
                "同名弓",
                "",
                "",
                "ObjectCode",
                "call RemoveItem(GetItemOfTypeFromUnitBJ(u,'I002'))",
            ],
        ],
    )


def test_refs_separates_same_named_codes_and_preserves_each_source(pack: Path) -> None:
    _references(pack)
    text = queries.execute_pack_query(
        PackQueryCliOptions(str(pack), "refs", "同名弓")
    ).render()
    assert "[I001] 同名弓  (物品)  共2处引用" in text
    assert "[I002] 同名弓  (物品)  共1处引用" in text
    assert "war3map.j:行1" in text and "war3map.wct(自定义代码).txt:行2" in text
    first, second = text.split("[I002]")
    assert "零消耗引用" in first and "零消耗引用" not in second
    assert "升级链在此终止" not in text and "recipe I001 / drop I001" in text


def test_refs_limit_counts_objects_and_keeps_all_references_of_selected_object(
    pack: Path,
) -> None:
    _references(pack)
    text = queries.execute_pack_query(
        PackQueryCliOptions(str(pack), "refs", "同名弓", limit=1)
    ).render()
    assert "GiveOne" in text and "GiveTwo" in text
    assert "[I002]" not in text and "其余 1 条未显示" in text
    one = queries.execute_pack_query(
        PackQueryCliOptions(str(pack), "refs", "I001", limit=1)
    ).render()
    assert "GiveOne" in one and "GiveTwo" in one and "已达 --limit" not in one


def test_refs_does_not_merge_identical_codes_from_different_categories(
    pack: Path,
) -> None:
    _rows(
        pack / "脚本对象码出现索引.tsv",
        [
            [
                "war3map.j",
                "1",
                "F",
                "I001",
                "",
                "物品",
                "同名对象",
                "",
                "",
                "CreateItem",
                "call CreateItem('I001',0,0)",
            ],
            [
                "war3map.j",
                "2",
                "F",
                "I001",
                "",
                "单位",
                "同名对象",
                "",
                "",
                "ObjectCode",
                "set u=CreateUnit(p,'I001',0,0,0)",
            ],
        ],
    )
    text = queries.execute_pack_query(
        PackQueryCliOptions(str(pack), "refs", "I001")
    ).render()
    assert "(物品)  共1处引用" in text and "(单位)  共1处引用" in text


@pytest.mark.parametrize("limit", [0, 1, 2, 3])
def test_affix_limits_count_definitions_with_different_output_lengths(
    pack: Path, limit: int
) -> None:
    _rows(
        pack / "词缀表.tsv",
        [
            ["词缀名", "倍率", "属性"],
            ["A特效", "1", ""],
            ["B属性", "2", "攻击力"],
            ["C特效", "3", ""],
        ],
    )
    text = queries.execute_pack_query(
        PackQueryCliOptions(str(pack), "affixes", "", limit=limit)
    ).render()
    assert "[A特效]" in text
    assert ("[B属性]" in text) == (limit != 1)
    assert ("[C特效]" in text) == (limit in {0, 3})
    if limit == 2:
        assert "词条等级 × 2" in text
    if limit in {1, 2}:
        assert f"其余 {3 - limit} 条未显示" in text
    else:
        assert "已达 --limit" not in text


def test_affixes_keep_same_named_definition_variants(pack: Path) -> None:
    _rows(
        pack / "词缀表.tsv",
        [
            ["词缀名", "倍率", "属性"],
            ["Straße", "1", "攻击力"],
            ["Straße", "2", "攻击力"],
            ["Straße", "3", "护甲"],
        ],
    )
    text = queries.execute_pack_query(
        PackQueryCliOptions(str(pack), "affixes", "STRASSE")
    ).render()
    assert text.count("[Straße]") == 3
    assert all(f"词条等级 × {i}" in text for i in range(1, 4))


@pytest.mark.parametrize("header", [None, "序号", "记录数"])
def test_registered_payload_search_preserves_first_record_and_legacy_headers(
    pack: Path, header: str | None
) -> None:
    rows = [["消息名", header, "记录JSON"]] if header is not None else []
    rows.extend(
        [
            ["event", "1", '{"hero":"Straße","value":1}'],
            ["other", "1", '{"hero":"Straße","value":2}'],
        ]
    )
    _rows(pack / "注册数据.tsv", rows)
    text = queries.execute_pack_query(
        PackQueryCliOptions(str(pack), "registered", "STRASSE")
    ).render()
    assert '"value":1' in text and '"value":2' in text
    names = queries._load_registered_names(pack)
    assert names == {"event": 1, "other": 1}


@pytest.mark.parametrize("query", ["", "needle"])
@pytest.mark.parametrize("limit", [0, 1, 3])
def test_registered_limits_disclose_actual_omissions_and_keep_full_payload(
    pack: Path, query: str, limit: int
) -> None:
    payload = '{"needle":"' + "全文" * 1500 + '"}'
    _rows(pack / "注册数据.tsv", [[f"event{i}", "1", payload] for i in range(3)])
    text = queries.execute_pack_query(
        PackQueryCliOptions(str(pack), "registered", query, limit=limit)
    ).render()
    if query:
        assert payload in text
    assert ("event2" in text) == (limit != 1)
    assert ("其余 2 条未显示" in text) == (limit == 1)


def test_message_named_like_header_is_still_a_real_record(pack: Path) -> None:
    _rows(pack / "注册数据.tsv", [["消息名", "1", '{"real":true}']])
    text = queries.execute_pack_query(
        PackQueryCliOptions(str(pack), "registered", "real")
    ).render()
    assert '{"real":true}' in text


@pytest.mark.parametrize("limit", [0, 1, 3, 4])
def test_quest_limits_have_exact_counts_and_full_text(pack: Path, limit: int) -> None:
    body = "任务全文" * 1000
    _rows(
        pack / "脚本字符串索引.tsv",
        [["war3map.j", str(i), "CreateQuestBJ", body] for i in range(3)],
    )
    text = queries.execute_pack_query(
        PackQueryCliOptions(str(pack), "quest", "任务全文", limit=limit)
    ).render()
    assert body in text
    assert text.count("CreateQuestBJ") == (1 if limit == 1 else 3)
    assert ("其余 2 条未显示" in text) == (limit == 1)


@pytest.mark.parametrize("limit", [0, 1, 2, 3])
def test_cmd_limits_count_whole_registrations_not_output_line_estimates(
    pack: Path, limit: int
) -> None:
    scripts = pack / "脚本可读文本"
    scripts.mkdir()
    body = 'call BJDebugMsg("' + "完整动作" * 1000 + '")'
    text = "\n".join(
        f"function Init{i} takes nothing returns nothing\n"
        f'call TriggerRegisterPlayerChatEvent(t{i},Player(0),"-all",true)\n'
        f"call TriggerAddAction(t{i},function Action{i})\nendfunction\n"
        f"function Action{i} takes nothing returns nothing\n{body}\nendfunction\n"
        for i in range(3)
    )
    (scripts / "war3map.j").write_text(text, encoding="utf-8")
    rendered = queries.execute_pack_query(
        PackQueryCliOptions(str(pack), "cmd", "-all", limit=limit)
    ).render()
    assert body in rendered
    count = 3 if limit == 0 else limit
    assert rendered.count('指令 "-all"') == count
    assert all(f"动作: function Action{i}" in rendered for i in range(count))
    assert ("已达 --limit" in rendered) == (limit in {1, 2})


def test_trigger_events_read_past_400_characters_without_borrowing_other_variables() -> (
    None
):
    text = (
        "set t = CreateTrigger()\n"
        "call TriggerAddCondition(t,Condition(function C))\n"
        + "call DoNothing()\n" * 100
        + "call TriggerRegisterAnyUnitEventBJ(t,EVENT_PLAYER_UNIT_PICKUP_ITEM)\n"
        + "call TriggerRegisterAnyUnitEventBJ(other,EVENT_PLAYER_UNIT_DEATH)\n"
    )
    assert queries._registration_events(
        "t", text.index("TriggerAddCondition"), text, 0
    ) == {"EVENT_PLAYER_UNIT_PICKUP_ITEM"}


def test_trigger_assignment_ends_registration_before_next_handlers_and_events() -> None:
    text = (
        "set t = CreateTrigger()\n"
        "call TriggerAddCondition(t,Condition(function First))\n"
        "call TriggerRegisterAnyUnitEventBJ(t,EVENT_PLAYER_UNIT_PICKUP_ITEM)\n"
        "set t = CreateTrigger()\n"
        "call TriggerRegisterAnyUnitEventBJ(t,EVENT_PLAYER_UNIT_DEATH)\n"
        "call TriggerAddAction(t,function Second)\n"
    )
    pos = text.index("TriggerAddCondition")
    assert queries._action_after_registration("t", pos, text, 0) == ""
    assert queries._registration_events("t", pos, text, 0) == {
        "EVENT_PLAYER_UNIT_PICKUP_ITEM"
    }


def test_cmd_reused_trigger_variables_keep_all_handlers_of_each_instance(
    pack: Path,
) -> None:
    text = """function Init takes nothing returns nothing
set t = CreateTrigger()
call TriggerRegisterPlayerChatEvent(t,Player(0),"-both",true)
call TriggerAddCondition(t,Condition(function CondA))
call TriggerAddCondition(t,Condition(function CondB))
call TriggerAddAction(t,function ActionA)
call TriggerAddAction(t,function ActionB)
set t = CreateTrigger()
call TriggerRegisterPlayerChatEvent(t,Player(0),"-both",true)
call TriggerAddAction(t,function ActionC)
endfunction
function CondA takes nothing returns boolean
return true
endfunction
function CondB takes nothing returns boolean
return true
endfunction
function ActionA takes nothing returns nothing
call DoNothing()
endfunction
function ActionB takes nothing returns nothing
call DoNothing()
endfunction
function ActionC takes nothing returns nothing
call DoNothing()
endfunction
"""
    scripts = pack / "脚本可读文本"
    scripts.mkdir()
    (scripts / "war3map.j").write_text(text, encoding="utf-8")
    output = queries.execute_pack_query(
        PackQueryCliOptions(str(pack), "cmd", "-both")
    ).render()
    _, first, second = output.split('指令 "-both"')
    assert all(
        "function " + name in first for name in ("CondA", "CondB", "ActionA", "ActionB")
    )
    assert "ActionC" not in first
    assert "function ActionC" in second and "function ActionA" not in second


def test_cmd_source_identity_prevents_same_named_handlers_from_other_files(
    pack: Path,
) -> None:
    scripts = pack / "脚本可读文本"
    scripts.mkdir()
    for source, marker in (("one.j", "alpha"), ("two.j", "beta")):
        (scripts / source).write_text(
            "function Init takes nothing returns nothing\n"
            'call TriggerRegisterPlayerChatEvent(t,Player(0),"-dup",true)\n'
            "call TriggerAddAction(t,function Action)\nendfunction\n"
            "function Action takes nothing returns nothing\n"
            f'call BJDebugMsg("{marker}   endfunction")\n'
            "call DoNothing()\nendfunction\n",
            encoding="utf-8",
        )
    output = queries.execute_pack_query(
        PackQueryCliOptions(str(pack), "cmd", "-dup")
    ).render()
    _, first, second = output.split('指令 "-dup"')
    assert "来源: one.j" in first and '"alpha   endfunction"' in first
    assert "来源: two.j" in second and '"beta   endfunction"' in second
    assert "beta" not in first and "alpha" not in second
    assert "call DoNothing()" in first and "call DoNothing()" in second


@pytest.mark.parametrize("bj", [False, True])
def test_cmd_balanced_arguments_cover_native_bj_forms_and_deep_players(
    pack: Path, bj: bool
) -> None:
    scripts = pack / "脚本可读文本"
    scripts.mkdir()
    player = "Player(" + "(" * 800 + "0" + ")" * 800 + ")"
    registration = (
        f'TriggerRegisterPlayerChatEventBJ\n(t,"-deep",true,{player})'
        if bj
        else f'TriggerRegisterPlayerChatEvent\n(t,{player},"-deep",true)'
    )
    (scripts / "war3map.j").write_text(
        "function Init takes nothing returns nothing\ncall "
        + registration
        + "\nendfunction\n",
        encoding="utf-8",
    )
    result = queries.execute_pack_query(PackQueryCliOptions(str(pack), "cmd", "-deep"))
    assert result.exit_code == 0 and '指令 "-deep" (精确' in result.render()


def test_cmd_ignores_comment_registrations_and_retains_dynamic_exactness(
    pack: Path,
) -> None:
    scripts = pack / "脚本可读文本"
    scripts.mkdir()
    (scripts / "war3map.j").write_text(
        '// call TriggerRegisterPlayerChatEvent(t,Player(0),"-fake",true)\n'
        'call TriggerRegisterPlayerChatEvent(t,Player(0),"-real",runtime_exact)\n',
        encoding="utf-8",
    )
    fake = queries.execute_pack_query(PackQueryCliOptions(str(pack), "cmd", "-fake"))
    assert fake.exit_code == 2
    real = queries.execute_pack_query(PackQueryCliOptions(str(pack), "cmd", "-real"))
    assert real.exit_code == 0 and "动态匹配: runtime_exact" in real.render()


def test_acquisition_rechecks_changed_script_even_with_same_size_and_mtime(
    pack: Path,
) -> None:
    _acquisition_pack(pack)
    first = queries.execute_pack_query(PackQueryCliOptions(str(pack), "drop", "I001"))
    assert "Unit1Actions" in first.render()
    script = pack / "脚本可读文本" / "war3map.j"
    stat = script.stat()
    script.write_text(
        script.read_text(encoding="utf-8").replace("'I001'", "'I099'"), encoding="utf-8"
    )
    os.utime(script, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    second = queries.execute_pack_query(PackQueryCliOptions(str(pack), "drop", "I001"))
    changed = queries.execute_pack_query(PackQueryCliOptions(str(pack), "drop", "I099"))
    assert "Unit1Actions" not in second.render()
    assert "Unit1Actions" in changed.render() and "I099" in changed.render()
