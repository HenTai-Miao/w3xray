"""Lua acquisition evidence remains complete, scoped and queryable."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from gametool import pack_query_cli as queries
from gametool.guide_report import format_guide_report
from gametool.map_data import GameObject, MapData
from gametool.pack_query_options import PackQueryCliOptions
from gametool.script_trigger_acquisition import (
    format_trigger_acquisitions,
    trigger_acquisitions,
)


def _script(
    condition: str = "GetUnitTypeId(GetDyingUnit())==FourCC('n001')",
    action: str = "CreateItem(FourCC('I001'),0,0)",
    event: str = "EVENT_PLAYER_UNIT_DEATH",
) -> str:
    return (
        f"local t=CreateTrigger() TriggerRegisterAnyUnitEventBJ(t,{event}) "
        f"TriggerAddCondition(t,Condition(function() return {condition} end)) "
        f"TriggerAddAction(t,function() {action} end)"
    )


def _map(scripts: dict[str, str]) -> MapData:
    md = MapData(path="synthetic.w3x", name="Lua产出测试", scripts=scripts)
    md.objects = {
        "物品": [
            GameObject("物品", "w3t", code, code, name, True)
            for code, name in (
                ("I001", "奖励甲"),
                ("I002", "奖励乙"),
                ("I003", "奖励丙"),
                ("I0BX", "测试宝箱"),
            )
        ],
        "单位": [
            GameObject("单位", "w3u", code, code, name, True)
            for code, name in (("n001", "怪物甲"), ("n002", "怪物乙"))
        ],
    }
    md.obj_index = {
        obj.obj_id: obj for objects in md.objects.values() for obj in objects
    }
    return md


@pytest.fixture
def pack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")
    (tmp_path / "脚本可读文本").mkdir()
    (tmp_path / "对象ID").mkdir()
    for category, objects in _map({}).objects.items():
        with (tmp_path / "对象ID" / f"{category}.tsv").open(
            "w", encoding="utf-8", newline=""
        ) as stream:
            csv.writer(stream, delimiter="\t").writerows(
                [
                    ["分类", "ID", "数值", "基础ID", "名称", "自定义", "说明"],
                    *[
                        [category, obj.obj_id, "1", obj.obj_id, obj.name, "是", ""]
                        for obj in objects
                    ],
                ]
            )
    return tmp_path


def _query(
    pack: Path, text: str, query: str, command: str = "drop", limit: int = 0
) -> str:
    (pack / "脚本可读文本" / "war3map.lua").write_text(text, encoding="utf-8")
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(pack), command, query, limit=limit)
    )
    assert result.exit_code == 0, result.render()
    return result.render()


@pytest.mark.parametrize("command", ["where", "drop"])
@pytest.mark.parametrize("code", ["n001", "I001"])
def test_death_event_and_anonymous_callbacks_are_queryable_from_source_and_item(
    pack: Path, command: str, code: str
) -> None:
    output = _query(pack, _script(), code, command)
    assert "脚本死亡触发产出线索" in output
    assert "怪物甲[n001]" in output and "奖励甲[I001]" in output
    assert "来源 war3map.lua" in output and "CreateItem(FourCC('I001'),0,0)" in output


@pytest.mark.parametrize(
    "event,kind",
    [
        ("EVENT_PLAYER_UNIT_PICKUP_ITEM", "拾取"),
        ("EVENT_PLAYER_UNIT_USE_ITEM", "使用"),
        ("EVENT_UNIT_PICKUP_ITEM", "拾取"),
        ("EVENT_UNIT_USE_ITEM", "使用"),
    ],
)
@pytest.mark.parametrize("target", ["I0BX", "I002"])
def test_item_input_and_reward_both_find_pickup_and_use_triggers(
    pack: Path, event: str, kind: str, target: str
) -> None:
    script = _script(
        "GetItemTypeId(GetManipulatedItem())==FourCC('I0BX')",
        "UnitAddItemById(GetTriggerUnit(),FourCC('I002'))",
        event,
    )
    output = _query(pack, script, target, "where")
    assert f"脚本{kind}触发产出线索" in output
    assert "测试宝箱[I0BX]" in output and "奖励乙[I002]" in output


@pytest.mark.parametrize(
    "expression,operation",
    [
        ("CreateItem(FourCC('I001'),0,0)", "创建"),
        ("CreateItemLoc(FourCC('I001'),Location(0,0))", "创建"),
        ("BlzCreateItemWithSkin(FourCC('I001'),0,0,FourCC('I003'))", "创建"),
        ("UnitAddItemById(GetTriggerUnit(),FourCC('I001'))", "发放"),
        ("UnitAddItemByIdSwapped(FourCC('I001'),GetTriggerUnit())", "发放"),
        ("UnitAddItemToSlotById(GetTriggerUnit(),FourCC('I001'),0)", "发放"),
        ("AddItemToStock(GetTriggerUnit(),FourCC('I001'),1,1)", "上架商店"),
        ("AddItemToStockBJ(FourCC('I001'),GetTriggerUnit(),1,1)", "上架商店"),
    ],
)
def test_native_item_parameter_positions_and_operations(
    expression: str, operation: str
) -> None:
    (row,) = trigger_acquisitions(_script(action=expression), lua=True)
    assert row.item_code == "I001" and row.operation == operation
    assert row.expression == expression


@pytest.mark.parametrize(
    "literal", ["FourCC('n001')", "0x6e303031", "1848651825", "_G.FourCC('n001')"]
)
@pytest.mark.parametrize("reverse", [False, True])
def test_selector_equality_supports_integer_ids_qualified_calls_and_reverse_operands(
    literal: str, reverse: bool
) -> None:
    getter = "_G.GetUnitTypeId(_G.GetDyingUnit())"
    condition = f"{literal}=={getter}" if reverse else f"{getter}=={literal}"
    (row,) = trigger_acquisitions(_script(condition), lua=True)
    assert row.unit_codes == ("n001",)


def test_if_elseif_and_else_rewards_keep_their_own_selector_scopes() -> None:
    text = _script(
        "true",
        "if GetUnitTypeId(GetDyingUnit())==FourCC('n001') then CreateItem(FourCC('I001'),0,0) elseif GetUnitTypeId(GetDyingUnit())==FourCC('n002') then CreateItem(FourCC('I002'),0,0) else CreateItem(FourCC('I003'),0,0) end",
    )
    rows = {row.item_code: row for row in trigger_acquisitions(text, lua=True)}
    assert rows["I001"].unit_codes == ("n001",)
    assert rows["I002"].unit_codes == ("n002",)
    assert rows["I003"].unit_codes == ()
    assert rows["I003"].conditions[-1].startswith("else（排除此前分支")
    output = "\n".join(
        format_trigger_acquisitions(tuple(rows.values()), str, target="n001")
    )
    assert "创建: I001[I001]" in output and "创建: I002[I002]" not in output


def test_nested_loops_do_not_end_the_surrounding_if_branch() -> None:
    text = _script(
        "true",
        "if GetUnitTypeId(GetDyingUnit())==FourCC('n001') then for i=1,10 do while true do CreateItem(FourCC('I001'),0,0) end end CreateItem(FourCC('I002'),0,0) end CreateItem(FourCC('I003'),0,0)",
    )
    rows = trigger_acquisitions(text, lua=True)
    assert [row.unit_codes for row in rows] == [("n001",), ("n001",), ()]


def test_reused_trigger_variables_do_not_mix_events_or_conditions(pack: Path) -> None:
    text = (
        _script()
        + " "
        + _script(
            "GetItemTypeId(GetManipulatedItem())==FourCC('I0BX')",
            "CreateItem(FourCC('I002'),0,0)",
            "EVENT_PLAYER_UNIT_USE_ITEM",
        )
    )
    output = _query(pack, text, "n001")
    assert "创建: 奖励甲[I001]" in output and "创建: 奖励乙[I002]" not in output


def test_same_named_callbacks_from_other_sources_never_supply_rewards(
    pack: Path,
) -> None:
    for filename, unit, item in (
        ("one.lua", "n001", "I001"),
        ("two.lua", "n002", "I002"),
    ):
        text = f"function Check() return GetUnitTypeId(GetDyingUnit())==FourCC('{unit}') end function Reward() CreateItem(FourCC('{item}'),0,0) end local t=CreateTrigger() TriggerRegisterAnyUnitEventBJ(t,EVENT_PLAYER_UNIT_DEATH) TriggerAddCondition(t,Condition(Check)) TriggerAddAction(t,Reward)"
        (pack / "脚本可读文本" / filename).write_text(text, encoding="utf-8")
    output = queries.execute_pack_query(
        PackQueryCliOptions(str(pack), "drop", "n001")
    ).render()
    assert "来源 one.lua" in output and "来源 two.lua" not in output
    assert "奖励甲[I001]" in output and "奖励乙[I002]" not in output


def test_nested_functions_do_not_supply_the_outer_action_rewards() -> None:
    text = _script(
        action="local unrelated=function() CreateItem(FourCC('I002'),0,0) end CreateItem(FourCC('I001'),0,0)"
    )
    rows = trigger_acquisitions(text, lua=True)
    assert [row.item_code for row in rows] == ["I001"]


def test_comments_strings_and_unrelated_getter_ids_are_not_death_selectors() -> None:
    text = (
        "-- "
        + _script()
        + "\n"
        + _script(
            "GetPlayerId(GetTriggerPlayer())==FourCC('n001')",
            "BJDebugMsg([[CreateItem(FourCC('I002'),0,0)]]) CreateItem(FourCC('I001'),0,0)",
        )
    )
    (row,) = trigger_acquisitions(text, lua=True)
    assert row.item_code == "I001" and row.unit_codes == ()


def test_dynamic_outputs_and_pool_placements_remain_visible_without_fabricated_items(
    pack: Path,
) -> None:
    text = _script(action="CreateItem(ChooseType(),0,0) PlaceRandomItem(udg_pool,0,0)")
    output = _query(pack, text, "n001")
    assert "动态物品码（未静态确定）" in output
    assert "随机奖池:" in output and "PlaceRandomItem(udg_pool,0,0)" in output


def test_ambiguous_callbacks_are_visible_as_candidates() -> None:
    text = "function Reward() CreateItem(FourCC('I001'),0,0) end function Reward() CreateItem(FourCC('I002'),0,0) end local t=CreateTrigger() TriggerRegisterAnyUnitEventBJ(t,EVENT_PLAYER_UNIT_DEATH) TriggerAddCondition(t,Condition(function() return GetUnitTypeId(GetDyingUnit())==FourCC('n001') end)) TriggerAddAction(t,Reward)"
    rows = trigger_acquisitions(text, lua=True)
    assert {row.item_code for row in rows} == {"I001", "I002"}
    assert all("回调同名歧义" in row.diagnostic for row in rows)


def test_unregistered_death_handler_is_labeled_as_a_static_clue() -> None:
    text = "function Reward() if GetUnitTypeId(GetDyingUnit())==FourCC('n001') then CreateItem(FourCC('I001'),0,0) end end"
    (row,) = trigger_acquisitions(text, lua=True)
    assert row.unit_codes == ("n001",) and "未找到本处理器的事件注册" in row.diagnostic


def test_source_call_multiplicity_and_positions_survive_identical_expressions() -> None:
    text = _script(
        action="CreateItem(FourCC('I001'),0,0) CreateItem(FourCC('I001'),0,0)"
    )
    rows = trigger_acquisitions(text, lua=True)
    assert len(rows) == 2 and rows[0].offset != rows[1].offset
    output = "\n".join(format_trigger_acquisitions(rows, str))
    assert output.count("原文: CreateItem(FourCC('I001'),0,0)") == 2


def test_full_random_evidence_is_shared_without_quadratic_output() -> None:
    count = 1800
    text = _script(
        action=" ".join(
            f"local roll{n}=GetRandomInt(1,{n + 2}) CreateItem(FourCC('I001'),0,0)"
            for n in range(count)
        )
    )
    rows = trigger_acquisitions(text, lua=True)
    assert len(rows) == count and rows[-1].random_count == count
    assert all(row.random_calls is rows[0].random_calls for row in rows)
    output = "\n".join(format_trigger_acquisitions(rows, str))
    assert output.count("随机调用") == count * 2
    assert "GetRandomInt(1,1801)" in output
    assert len(output) < count * 500


def test_nested_branch_conditions_have_no_depth_ceiling() -> None:
    depth = 1400
    text = _script(
        action="if true then " * depth
        + "CreateItem(FourCC('I001'),0,0) "
        + "end " * depth
    )
    (row,) = trigger_acquisitions(text, lua=True)
    assert row.unit_codes == ("n001",) and len(row.conditions) == depth + 1


def test_guide_death_and_loot_sections_use_the_same_complete_lua_evidence() -> None:
    md = _map(
        {
            "war3map.lua": _script()
            + " "
            + _script(
                "GetItemTypeId(GetManipulatedItem())==FourCC('I0BX')",
                "CreateItem(FourCC('I002'),0,0)",
                "EVENT_PLAYER_UNIT_USE_ITEM",
            )
        }
    )
    drops = format_guide_report(md, "drops")
    loot = format_guide_report(md, "loot")
    assert "脚本死亡触发产出线索" in drops and "奖励甲[I001]" in drops
    assert (
        "脚本使用触发产出线索" in loot
        and "测试宝箱[I0BX]" in loot
        and "奖励乙[I002]" in loot
    )


def test_explicit_limit_does_not_cut_the_selected_triggers_body_or_rewards(
    pack: Path,
) -> None:
    count = 75
    text = _script(
        action=" ".join("CreateItem(FourCC('I001'),0,0)" for _ in range(count))
    )
    output = _query(pack, text, "n001", limit=1)
    assert output.count("原文: CreateItem(FourCC('I001'),0,0)") == count


def test_lua_functions_named_after_jass_keywords_do_not_change_branch_scopes() -> None:
    text = _script(
        "true",
        "if GetUnitTypeId(GetDyingUnit())==FourCC('n001') then loop() endif() endloop() CreateItem(FourCC('I001'),0,0) end CreateItem(FourCC('I002'),0,0)",
    )
    rows = trigger_acquisitions(text, lua=True)
    assert [row.unit_codes for row in rows] == [("n001",), ()]


def test_every_registered_event_dimension_remains_visible_in_queries_and_guide(
    pack: Path,
) -> None:
    text = "local t=CreateTrigger() TriggerRegisterAnyUnitEventBJ(t,EVENT_PLAYER_UNIT_DEATH) TriggerRegisterAnyUnitEventBJ(t,EVENT_PLAYER_UNIT_PICKUP_ITEM) TriggerRegisterAnyUnitEventBJ(t,EVENT_PLAYER_UNIT_USE_ITEM) TriggerAddCondition(t,Condition(function() return GetItemTypeId(GetManipulatedItem())==FourCC('I0BX') end)) TriggerAddAction(t,function() CreateItem(FourCC('I001'),0,0) end)"
    rows = trigger_acquisitions(text, lua=True)
    assert {row.kind for row in rows} == {"死亡", "拾取", "使用"}
    output = _query(pack, text, "I001")
    assert all(f"脚本{kind}触发产出线索" in output for kind in ("死亡", "拾取", "使用"))
    md = _map({"war3map.lua": text})
    assert "脚本死亡触发产出线索" in format_guide_report(md, "drops")
    loot = format_guide_report(md, "loot")
    assert "脚本拾取触发产出线索" in loot and "脚本使用触发产出线索" in loot


@pytest.mark.parametrize(
    "condition",
    [
        "GetUnitTypeId(GetDyingUnit())==FourCC('n001')+1",
        "FourCC('n001')+1==GetUnitTypeId(GetDyingUnit())",
        "FourCC('n001')==GetUnitTypeId(GetDyingUnit())+1",
        "1+GetUnitTypeId(GetDyingUnit())==FourCC('n001')",
    ],
)
def test_arithmetic_comparisons_are_not_reinterpreted_as_literal_unit_ids(
    condition: str,
) -> None:
    (row,) = trigger_acquisitions(_script(condition), lua=True)
    assert row.unit_codes == ()


def test_existing_jass_callbacks_can_still_link_across_exported_sources(
    pack: Path,
) -> None:
    texts = {
        "conditions.j": "function Trig_SplitConditions takes nothing returns boolean\nreturn GetUnitTypeId(GetDyingUnit())=='n001'\nendfunction\n",
        "actions.j": "function Trig_SplitActions takes nothing returns nothing\ncall CreateItem('I001',0,0)\nendfunction\n",
        "init.j": "function Init takes nothing returns nothing\ncall TriggerRegisterAnyUnitEventBJ(t,EVENT_PLAYER_UNIT_DEATH)\ncall TriggerAddCondition(t,Condition(function Trig_SplitConditions))\ncall TriggerAddAction(t,function Trig_SplitActions)\nendfunction\n",
    }
    for source, text in texts.items():
        (pack / "脚本可读文本" / source).write_text(text, encoding="utf-8")
    output = queries.execute_pack_query(
        PackQueryCliOptions(str(pack), "drop", "n001")
    ).render()
    assert "I001" in output and "Trig_Split" in output


def test_lua_display_strings_cannot_supply_jass_handler_bodies(pack: Path) -> None:
    real = "function Trig_TestConditions takes nothing returns boolean\nreturn GetUnitTypeId(GetDyingUnit())=='n001'\nendfunction\nfunction Trig_TestActions takes nothing returns nothing\ncall CreateItem('I001',0,0)\nendfunction\nfunction Init takes nothing returns nothing\ncall TriggerAddCondition(t,Condition(function Trig_TestConditions))\ncall TriggerAddAction(t,function Trig_TestActions)\nendfunction\n"
    (pack / "脚本可读文本" / "war3map.j").write_text(real, encoding="utf-8")
    (pack / "脚本可读文本" / "aaa.lua").write_text(
        "BJDebugMsg([[function Trig_TestActions takes nothing returns nothing\ncall CreateItem('I002',0,0)\nendfunction]])",
        encoding="utf-8",
    )
    output = queries.execute_pack_query(
        PackQueryCliOptions(str(pack), "drop", "n001")
    ).render()
    assert "I001" in output and "I002" not in output


def test_unclosed_lua_action_remains_a_visible_diagnostic() -> None:
    text = "function Reward() if GetUnitTypeId(GetDyingUnit())==FourCC('n001') then CreateItem(FourCC('I001'),0,0) end"
    (row,) = trigger_acquisitions(text, lua=True)
    assert row.item_code == "I001" and "范围未闭合" in row.diagnostic


@pytest.mark.parametrize(
    "section,event,condition",
    [
        (
            "drops",
            "EVENT_PLAYER_UNIT_DEATH",
            "GetUnitTypeId(GetDyingUnit())==FourCC('n001')",
        ),
        (
            "loot",
            "EVENT_PLAYER_UNIT_USE_ITEM",
            "GetItemTypeId(GetManipulatedItem())==FourCC('I0BX')",
        ),
    ],
)
def test_guide_keeps_each_repeated_source_call_in_its_evidence_block(
    section: str, event: str, condition: str
) -> None:
    expression = "CreateItem(FourCC('I001'),0,0)"
    text = _script(condition, " ".join(expression for _ in range(4)), event)
    output = format_guide_report(_map({"war3map.lua": text}), section)
    assert output.count("原文: " + expression) == 4
    assert output.count("创建: 奖励甲[I001]") == 4
