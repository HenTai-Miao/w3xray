"""Conservative JASS, Lua, registration, and WTG item reward relations."""

from w3xtool.item_relation_models import (
    ItemRelationKind,
    RelationCompleteness,
    RelationConfidence,
)
from w3xtool.item_relation_scripts import build_script_item_relations
from w3xtool.map_data import GameObject, MapData
from w3xtool.wtg_models import (
    TriggerEcaFunction,
    TriggerEcaParameter,
    TriggerTreeSummary,
)


def _item(object_id: str, name: str) -> GameObject:
    return GameObject("物品", "w3t", object_id, object_id, name, True)


def _map_with_items(*items: GameObject, scripts: dict[str, str] | None = None) -> MapData:
    md = MapData(path="x.w3x", name="奖励图", scripts=scripts or {})
    md.objects = {"物品": list(items)}
    md.obj_index = {item.obj_id: item for item in items}
    return md


def test_fixed_reward_calls_keep_item_source_function_line_recipient_and_location() -> None:
    # Given: fixed JASS recipient and coordinate reward calls.
    script = "\n".join((
        "function Reward takes nothing returns nothing",
        "    call UnitAddItemById(GetTriggerUnit(), 'I001')",
        "    call CreateItem('I002', 128.0, -64.0)",
        "endfunction",
    ))
    md = _map_with_items(
        _item("I001", "单位奖励"),
        _item("I002", "地面奖励"),
        scripts={"war3map.j": script},
    )

    # When: script reward evidence is indexed.
    rows = build_script_item_relations(md)

    # Then: item identity, source, line, recipient, and static coordinates survive.
    assert {(row.item.object_id, row.evidence.source, row.evidence.line) for row in rows} == {
        ("I001", "war3map.j", 2),
        ("I002", "war3map.j", 3),
    }
    by_item = {row.item.object_id: row for row in rows}
    assert "GetTriggerUnit()" in by_item["I001"].evidence.location
    assert (by_item["I002"].x, by_item["I002"].y) == (128.0, -64.0)
    assert all(row.evidence.function == "Reward" for row in rows)
    assert all(row.confidence is RelationConfidence.CONFIRMED for row in rows)


def test_lua_fourcc_reward_is_confirmed_without_treating_strings_as_calls() -> None:
    # Given: one real Lua call and one call-shaped display string.
    script = "\n".join((
        "function Reward()",
        '    UnitAddItemById(GetTriggerUnit(), FourCC("I003"))',
        '    BJDebugMsg("CreateItem(FourCC(\\"I999\\"), 0, 0)")',
        "end",
    ))
    md = _map_with_items(_item("I003", "Lua奖励"), scripts={"war3map.lua": script})

    # When: script reward evidence is indexed.
    rows = build_script_item_relations(md)

    # Then: only the actual fixed-code call becomes a relation.
    assert [(row.item.object_id, row.evidence.line) for row in rows] == [("I003", 2)]
    assert rows[0].confidence is RelationConfidence.CONFIRMED


def test_death_event_context_is_inferred_not_claimed_as_direct_monster_drop() -> None:
    # Given: a reward action is exactly joined to a death-event trigger handle.
    script = "\n".join((
        "function Reward takes nothing returns nothing",
        "    call UnitAddItemById(GetTriggerUnit(), 'I001')",
        "endfunction",
        "function InitReward takes nothing returns nothing",
        "    call TriggerRegisterAnyUnitEventBJ(t, EVENT_PLAYER_UNIT_DEATH)",
        "    call TriggerAddAction(t, function Reward)",
        "endfunction",
    ))
    md = _map_with_items(_item("I001", "死亡奖励"), scripts={"war3map.j": script})

    # When: registration context and reward calls are joined.
    (row,) = build_script_item_relations(md)

    # Then: the event link lowers confidence and never becomes a direct monster drop.
    assert row.kind is ItemRelationKind.SCRIPT_REWARD
    assert row.confidence is RelationConfidence.INFERRED
    assert "EVENT_PLAYER_UNIT_DEATH" in row.evidence.raw


def test_dynamic_or_unrelated_item_calls_never_become_confirmed_rewards() -> None:
    # Given: comments, a handle-based API, an unknown variable, and a dynamic expression.
    script = "\n".join((
        "// call UnitAddItemById(u, 'I001')",
        "call UnitAddItem(u, CreateItem('I002', 0, 0))",
        "call UnitAddItemById(u, rewardType)",
        "call UnitAddItemById(u, PickItem('I003'))",
    ))
    md = _map_with_items(_item("I003", "动态线索"), scripts={"war3map.j": script})

    # When: bounded call signatures are applied.
    rows = build_script_item_relations(md)

    # Then: only the concrete code inside a dynamic argument remains, explicitly as a clue.
    assert len(rows) == 1
    assert rows[0].item.object_id == "I003"
    assert rows[0].confidence is RelationConfidence.CLUE
    assert rows[0].completeness is RelationCompleteness.PARTIAL


def test_wtg_fixed_item_parameter_keeps_recursive_trigger_ordinal_and_offset() -> None:
    # Given: an enabled item action is nested inside a parent WTG ECA node.
    action = TriggerEcaFunction(
        trigger_name="奖励触发",
        function_type=2,
        name="CreateItemLoc",
        is_enabled=True,
        parameters=(
            TriggerEcaParameter(0, "I777", expected_type="itemcode", source_offset=0x128),
            TriggerEcaParameter(2, "GetRectCenter", expected_type="location"),
        ),
        children=(),
        depth=1,
        ordinal=4,
        branch=2,
        source_offset=0x120,
    )
    parent = TriggerEcaFunction(
        trigger_name="奖励触发",
        function_type=2,
        name="IfThenElse",
        is_enabled=True,
        parameters=(),
        children=(action,),
        ordinal=1,
        source_offset=0x80,
    )
    md = _map_with_items(_item("I777", "触发奖励"))
    md.trigger_summary = TriggerTreeSummary(
        version=7,
        is_reforged=False,
        category_count=0,
        variable_count=0,
        trigger_count=1,
        comment_count=0,
        script_count=0,
        categories=(),
        variables=(),
        triggers=(),
        eca_functions=(parent,),
    )

    # When: recursive WTG actions are indexed.
    (row,) = build_script_item_relations(md)

    # Then: fixed code, trigger, branch, ordinal, and binary offset remain explicit.
    assert row.item.object_id == "I777"
    assert row.evidence.source == "war3map.wtg"
    assert row.evidence.trigger == "奖励触发"
    assert row.evidence.location == "ECA 4 分支2 @ 0x120"
    assert row.confidence is RelationConfidence.CONFIRMED
