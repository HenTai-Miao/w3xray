"""Complete, source-attributed JASS/Lua trigger instances and command callbacks."""

from pathlib import Path

import pytest

from gametool.item_relation_models import RelationConfidence
from gametool.item_relation_scripts import build_script_call_item_relations
from gametool.map_data import GameObject, MapData
from gametool.pack_query_cli import execute_pack_query
from gametool.pack_query_options import PackQueryCliOptions
from gametool.script_trigger_bindings import script_trigger_bindings
from gametool.script_trigger_registration_index import (
    build_script_trigger_registration_index,
    format_script_trigger_registration_index_tsv,
)


def _map(text: str, *, lua: bool = True) -> MapData:
    md = MapData(path="synthetic.w3x", name="触发关联回归")
    md.scripts = {"war3map.lua" if lua else "war3map.j": text}
    md.objects = {
        "物品": [
            GameObject("物品", "w3t", code, code, code, True)
            for code in ("I001", "I002")
        ]
    }
    md.obj_index = {item.obj_id: item for item in md.objects["物品"]}
    return md


def _query(
    tmp_path: Path,
    text: str,
    query: str = "-test",
    *,
    lua: bool = True,
    limit: int = 0,
) -> str:
    scripts = tmp_path / "脚本可读文本"
    scripts.mkdir(exist_ok=True)
    (scripts / ("war3map.lua" if lua else "war3map.j")).write_text(
        text, encoding="utf-8"
    )
    return execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "cmd", query, limit=limit)
    ).render()


def test_lua_cmd_keeps_all_named_assigned_and_anonymous_callbacks(
    tmp_path: Path,
) -> None:
    payload = "完整回调" * 2600
    script = f"""function Init()
local t=CreateTrigger()
local function Check() return true end
local Action=function() BJDebugMsg('assigned') end
_G.TriggerRegisterPlayerChatEvent(t,Player(0),'-test',true)
TriggerAddCondition(t,Condition(Check))
TriggerAddCondition(t,Condition(function() return GetPlayerId(GetTriggerPlayer())==0 end))
TriggerAddAction(t,Action)
TriggerAddAction(t,function() BJDebugMsg([=[{payload}]=]) end)
end"""
    output = _query(tmp_path, script)
    assert '指令 "-test" (精确, 注册1个玩家位)' in output
    assert "local function Check() return true end" in output
    assert "function() BJDebugMsg('assigned') end" in output
    assert "function() return GetPlayerId(GetTriggerPlayer())==0 end" in output
    assert payload in output and "未找到 TriggerAddAction" not in output


@pytest.mark.parametrize("lua", [True, False])
def test_reassigned_trigger_has_separate_complete_command_blocks(
    tmp_path: Path, lua: bool
) -> None:
    script = (
        "function Init() local t=CreateTrigger() TriggerRegisterPlayerChatEvent(t,Player(0),'-test',true) "
        "TriggerAddAction(t,function() BJDebugMsg('FIRST') end) t=CreateTrigger() "
        "TriggerRegisterPlayerChatEvent(t,Player(1),'-test',true) TriggerAddAction(t,function() BJDebugMsg('SECOND') end) end"
        if lua
        else 'function Init takes nothing returns nothing set t=CreateTrigger() call TriggerRegisterPlayerChatEvent(t,Player(0),"-test",true) '
        'call TriggerAddAction(t,function First) set t=CreateTrigger() call TriggerRegisterPlayerChatEvent(t,Player(1),"-test",true) '
        "call TriggerAddAction(t,function Second) endfunction "
        'function First takes nothing returns nothing call BJDebugMsg("FIRST") endfunction '
        'function Second takes nothing returns nothing call BJDebugMsg("SECOND") endfunction'
    )
    output = _query(tmp_path, script, lua=lua)
    _, first, second = output.split('指令 "-test"')
    assert "FIRST" in first and "SECOND" not in first
    assert "SECOND" in second and "FIRST" not in second


def test_array_handles_preserve_string_keys_and_assignment_windows(
    tmp_path: Path,
) -> None:
    script = """function Init()
local t={}
t['a b']=CreateTrigger()
t['ab']=CreateTrigger()
TriggerRegisterPlayerChatEvent(t [ 'a b' ],Player(0),'-test',true)
TriggerAddAction(t['a b'],function() BJDebugMsg('SPACE_KEY') end)
TriggerAddAction(t['ab'],function() BJDebugMsg('OTHER_KEY') end)
t['a b']=CreateTrigger()
TriggerAddAction(t['a b'],function() BJDebugMsg('AFTER_RESET') end)
end"""
    output = _query(tmp_path, script)
    assert "SPACE_KEY" in output
    assert "OTHER_KEY" not in output and "AFTER_RESET" not in output


def test_sibling_local_handlers_and_initializers_on_one_line_do_not_mix(
    tmp_path: Path,
) -> None:
    script = " ".join(
        f"function Init{n}() local function Action() BJDebugMsg('OWNER{n}') end local t=CreateTrigger() "
        f"TriggerRegisterPlayerChatEvent(t,Player(0),'-test',true) TriggerAddAction(t,Action) end"
        for n in range(2)
    )
    output = _query(tmp_path, script)
    _, first, second = output.split('指令 "-test"')
    assert "OWNER0" in first and "OWNER1" not in first
    assert "OWNER1" in second and "OWNER0" not in second


def test_ambiguous_callbacks_retain_every_candidate_with_diagnostic(
    tmp_path: Path,
) -> None:
    script = """function Action() BJDebugMsg('ONE') end
function Action() BJDebugMsg('TWO') end
function Init() TriggerRegisterPlayerChatEvent(t,Player(0),'-test',true) TriggerAddAction(t,Action) end"""
    output = _query(tmp_path, script)
    assert "回调同名歧义：2 个候选" in output
    assert "ONE" in output and "TWO" in output


@pytest.mark.parametrize(
    "expression", ["handlers[choice]", "ExternalHandler", "ChooseHandler()"]
)
def test_unresolved_callback_expression_has_a_reason_in_query_and_export(
    tmp_path: Path, expression: str
) -> None:
    script = f"TriggerRegisterPlayerChatEvent(t,Player(0),'-test',true) TriggerAddAction(t,{expression})"
    output = _query(tmp_path, script)
    assert expression in output and "动作诊断:" in output
    registrations = build_script_trigger_registration_index(_map(script)).registrations
    assert (
        registrations[-1].callback_diagnostic and registrations[-1].target == expression
    )


def test_trigger_index_exports_exact_positions_anonymous_callbacks_and_timers() -> None:
    script = "function Init() local t=CreateTrigger() TriggerAddAction(t,function() DoNothing() end) TimerStart(timer,1,true,function() DoNothing() end) end"
    index = build_script_trigger_registration_index(_map(script))
    assert len(index.registrations) == 2
    for row in index.registrations:
        assert row.target.startswith("<匿名@") and len(row.callback_offsets) == 1
        assert script[row.offset :].startswith(row.api)
        assert script[row.callback_offsets[0] :].startswith("function()")
        assert row.scope_offset == 0
    text = format_script_trigger_registration_index_tsv(index)
    assert "触发器赋值偏移\t回调偏移\t回调诊断\t回调表达式" in text
    assert all(len(line.split("\t")) == 16 for line in text.splitlines())


@pytest.mark.parametrize("lua", [True, False])
def test_death_context_does_not_leak_across_reused_handles(lua: bool) -> None:
    script = (
        "function First() CreateItem(FourCC('I001'),0,0) end function Second() CreateItem(FourCC('I002'),0,0) end "
        "function Init() local t=CreateTrigger() TriggerRegisterAnyUnitEventBJ(t,EVENT_PLAYER_UNIT_DEATH) TriggerAddAction(t,First) "
        "t=CreateTrigger() TriggerRegisterAnyUnitEventBJ(t,EVENT_PLAYER_UNIT_PICKUP_ITEM) TriggerAddAction(t,Second) end"
        if lua
        else "function First takes nothing returns nothing call CreateItem('I001',0,0) endfunction "
        "function Second takes nothing returns nothing call CreateItem('I002',0,0) endfunction "
        "function Init takes nothing returns nothing set t=CreateTrigger() call TriggerRegisterAnyUnitEventBJ(t,EVENT_PLAYER_UNIT_DEATH) call TriggerAddAction(t,function First) "
        "set t=CreateTrigger() call TriggerRegisterAnyUnitEventBJ(t,EVENT_PLAYER_UNIT_PICKUP_ITEM) call TriggerAddAction(t,function Second) endfunction"
    )
    rows = {
        row.item.object_id: row
        for row in build_script_call_item_relations(_map(script, lua=lua))
    }
    assert rows["I001"].confidence is RelationConfidence.INFERRED
    assert "EVENT_PLAYER_UNIT_DEATH" in rows["I001"].evidence.raw
    assert rows["I002"].confidence is RelationConfidence.CONFIRMED
    assert "EVENT_PLAYER_UNIT_DEATH" not in rows["I002"].evidence.raw


def test_death_context_uses_exact_nested_callback_definition() -> None:
    script = """function InitA()
local function Reward() CreateItem(FourCC('I001'),0,0) end
local t=CreateTrigger() TriggerRegisterAnyUnitEventBJ(t,EVENT_PLAYER_UNIT_DEATH) TriggerAddAction(t,Reward)
end
function InitB()
local function Reward() CreateItem(FourCC('I002'),0,0) end
local t=CreateTrigger() TriggerAddAction(t,Reward)
end"""
    rows = {
        row.item.object_id: row
        for row in build_script_call_item_relations(_map(script))
    }
    assert rows["I001"].confidence is RelationConfidence.INFERRED
    assert rows["I002"].confidence is RelationConfidence.CONFIRMED


def test_anonymous_death_action_links_its_reward_without_promoting_direct_drop() -> (
    None
):
    script = "local t=CreateTrigger() TriggerRegisterAnyUnitEventBJ(t,EVENT_PLAYER_UNIT_DEATH) TriggerAddAction(t,function() CreateItem(FourCC('I001'),0,0) end)"
    (row,) = build_script_call_item_relations(_map(script))
    assert (
        row.confidence is RelationConfidence.INFERRED
        and "EVENT_PLAYER_UNIT_DEATH" in row.evidence.raw
    )


def test_ambiguous_handler_is_not_assigned_a_definite_death_context() -> None:
    script = "function Reward() CreateItem(FourCC('I001'),0,0) end function Reward() CreateItem(FourCC('I002'),0,0) end TriggerRegisterAnyUnitEventBJ(t,EVENT_PLAYER_UNIT_DEATH) TriggerAddAction(t,Reward)"
    rows = build_script_call_item_relations(_map(script))
    assert len(rows) == 2 and all(
        row.confidence is RelationConfidence.CONFIRMED for row in rows
    )


def test_lua_callbacks_and_trigger_instances_have_no_record_ceiling(
    tmp_path: Path,
) -> None:
    count = 2100
    script = (
        "function Init() "
        + " ".join(
            "local t=CreateTrigger() TriggerRegisterPlayerChatEvent(t,Player(0),'-test',true) "
            f"TriggerAddAction(t,function() BJDebugMsg('REWARD{n}') end)"
            for n in range(count)
        )
        + " end"
    )
    output = _query(tmp_path, script)
    assert output.count('指令 "-test"') == count
    assert all(f"'REWARD{n}'" in output for n in range(count))
    limited = execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "cmd", "-test", limit=2)
    ).render()
    assert limited.count('指令 "-test"') == 2 and str(count - 2) in limited


def test_array_assignment_matching_has_no_nesting_ceiling() -> None:
    handle = "t[" + "a[" * 1200 + "0" + "]" * 1200 + "]"
    script = f"{handle}=CreateTrigger() TriggerRegisterPlayerChatEvent({handle},Player(0),'-test',true) TriggerAddAction({handle},function() DoNothing() end)"
    bindings = script_trigger_bindings(script, lua=True)
    assert len(bindings.sites) == 2 and len(bindings.instances) == 1
    assert bindings.sites[0].instance[2] == script.index("=")


def test_replacing_parent_table_ends_an_array_trigger_instance(tmp_path: Path) -> None:
    script = "local t={} t[1]=CreateTrigger() TriggerRegisterPlayerChatEvent(t[1],Player(0),'-test',true) TriggerAddAction(t[1],function() BJDebugMsg('BEFORE') end) t={} TriggerAddAction(t[1],function() BJDebugMsg('AFTER') end)"
    output = _query(tmp_path, script)
    assert "BEFORE" in output and "AFTER" not in output


def test_dynamic_trigger_handles_have_diagnostics_and_do_not_borrow_handlers(
    tmp_path: Path,
) -> None:
    script = "TriggerRegisterPlayerChatEvent(ChooseTrigger(),Player(0),'-test',true) TriggerAddAction(ChooseTrigger(),function() BJDebugMsg('UNRELATED') end)"
    output = _query(tmp_path, script)
    assert "动态句柄表达式" in output and "UNRELATED" not in output
    rows = build_script_trigger_registration_index(_map(script)).registrations
    assert all(row.binding_diagnostic for row in rows)


def test_dynamic_array_index_is_a_visible_clue_without_a_definite_death_link(
    tmp_path: Path,
) -> None:
    script = "local t={} TriggerRegisterPlayerChatEvent(t[index],Player(0),'-test',true) TriggerRegisterAnyUnitEventBJ(t[index],EVENT_PLAYER_UNIT_DEATH) TriggerAddAction(t[index],function() CreateItem(FourCC('I001'),0,0) end)"
    output = _query(tmp_path, script)
    assert "动态索引" in output and "CreateItem" in output
    (row,) = build_script_call_item_relations(_map(script))
    assert row.confidence is RelationConfidence.CONFIRMED
    assert "EVENT_PLAYER_UNIT_DEATH" not in row.evidence.raw


def test_handler_callback_body_does_not_supply_the_outer_event_or_handle() -> None:
    script = "TriggerAddAction(t,function() local t=CreateTrigger() TriggerRegisterAnyUnitEventBJ(t,EVENT_PLAYER_UNIT_DEATH) end) TriggerAddAction(t,function() CreateItem(FourCC('I001'),0,0) end)"
    (row,) = build_script_call_item_relations(_map(script))
    assert row.confidence is RelationConfidence.CONFIRMED
    assert "EVENT_PLAYER_UNIT_DEATH" not in row.evidence.raw


@pytest.mark.parametrize("lua", [True, False])
def test_repeated_callback_registrations_disclose_their_full_multiplicity(
    tmp_path: Path, lua: bool
) -> None:
    script = (
        "function Check() return true end function Action() BJDebugMsg('DUPLICATE_MARK') end "
        "TriggerRegisterPlayerChatEvent(t,Player(0),'-test',true) "
        + "TriggerAddCondition(t,Condition(Check)) " * 2
        + "TriggerAddAction(t,Action) " * 3
        if lua
        else "function Check takes nothing returns boolean return true endfunction "
        'function Action takes nothing returns nothing call BJDebugMsg("DUPLICATE_MARK") endfunction '
        'call TriggerRegisterPlayerChatEvent(t,Player(0),"-test",true) '
        + "call TriggerAddCondition(t,Condition(function Check)) " * 2
        + "call TriggerAddAction(t,function Action) " * 3
    )
    output = _query(tmp_path, script, lua=lua)
    assert "条件注册: 同一回调 2 次" in output
    assert "动作注册: 同一回调 3 次" in output
    assert output.count("DUPLICATE_MARK") == 1


def test_lua_table_fields_do_not_reassign_same_named_trigger_variables(
    tmp_path: Path,
) -> None:
    script = "local t=CreateTrigger() TriggerRegisterPlayerChatEvent(t,Player(0),'-test',true) local data={t=42,nested={t=99}} TriggerAddAction(t,function() BJDebugMsg('RIGHT_HANDLER') end)"
    output = _query(tmp_path, script)
    assert "RIGHT_HANDLER" in output


def test_lua_multiple_assignment_closes_every_reassigned_trigger(
    tmp_path: Path,
) -> None:
    script = "local t,u=CreateTrigger(),CreateTrigger() TriggerRegisterPlayerChatEvent(t,Player(0),'-test',true) TriggerAddAction(t,function() BJDebugMsg('BEFORE') end) t,u=CreateTrigger(),CreateTrigger() TriggerAddAction(t,function() BJDebugMsg('AFTER') end)"
    output = _query(tmp_path, script)
    assert "BEFORE" in output and "AFTER" not in output


def test_lua_function_in_table_constructor_still_tracks_its_local_assignments(
    tmp_path: Path,
) -> None:
    script = "local callbacks={run=function() local t=CreateTrigger() TriggerRegisterPlayerChatEvent(t,Player(0),'-test',true) TriggerAddAction(t,function() BJDebugMsg('TABLE_CALLBACK') end) t=CreateTrigger() TriggerAddAction(t,function() BJDebugMsg('OTHER_TRIGGER') end) end}"
    output = _query(tmp_path, script)
    assert "TABLE_CALLBACK" in output and "OTHER_TRIGGER" not in output
