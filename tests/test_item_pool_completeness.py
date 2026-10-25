"""Native item pools keep their full membership, weights and lifecycle evidence."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from gametool import pack_query_cli as queries
from gametool.guide_report import format_guide_report
from gametool.map_data import GameObject, MapData
from gametool.pack_query_options import PackQueryCliOptions
from gametool.script_item_pools import item_pool_index
from gametool.script_trigger_acquisition import (
    format_trigger_acquisitions,
    trigger_acquisitions,
)


def _snapshots(text: str):
    return tuple(
        snapshots for snapshots in item_pool_index(text, lua=True).placements.values()
    )


def _trigger(
    body: str,
    event: str = "EVENT_PLAYER_UNIT_DEATH",
    condition: str = "GetUnitTypeId(GetDyingUnit())==FourCC('n001')",
) -> str:
    return f"local t=CreateTrigger() TriggerRegisterAnyUnitEventBJ(t,{event}) TriggerAddCondition(t,Condition(function() return {condition} end)) TriggerAddAction(t,function() {body} end)"


def _add(code: str, weight: str = "10", pool: str = "p") -> str:
    return f"ItemPoolAddItemType({pool},FourCC('{code}'),{weight}) "


def _map(text: str) -> MapData:
    md = MapData(path="synthetic.w3x", name="奖池测试", scripts={"war3map.lua": text})
    md.objects = {
        "物品": [
            GameObject("物品", "w3t", code, code, name, True)
            for code, name in (
                ("I001", "奖品甲"),
                ("I002", "奖品乙"),
                ("I003", "奖品丙"),
                ("I0BX", "宝箱"),
            )
        ],
        "单位": [GameObject("单位", "w3u", "n001", "n001", "测试怪物", True)],
    }
    md.obj_index = {
        obj.obj_id: obj for objects in md.objects.values() for obj in objects
    }
    return md


@pytest.fixture
def pack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")
    (tmp_path / "对象ID").mkdir()
    (tmp_path / "脚本可读文本").mkdir()
    for category, objects in _map("").objects.items():
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


@pytest.mark.parametrize("command", ["where", "drop"])
@pytest.mark.parametrize("target", ["n001", "I001", "I002"])
def test_pool_members_are_queryable_from_monster_and_each_item(
    pack: Path, command: str, target: str
) -> None:
    text = _trigger(
        "local p=CreateItemPool() "
        + _add("I001")
        + _add("I002", "30")
        + "PlaceRandomItem(p,0,0)"
    )
    (pack / "脚本可读文本" / "war3map.lua").write_text(text, encoding="utf-8")
    result = queries.execute_pack_query(PackQueryCliOptions(str(pack), command, target))
    assert result.exit_code == 0
    output = result.render()
    assert "成员: 奖品甲[I001]; 原文权重 10 / 40" in output
    assert "成员: 奖品乙[I002]; 原文权重 30 / 40" in output
    assert "非全部同时产出" in output and "原文总权重: 40" in output


@pytest.mark.parametrize(
    "weights,total",
    [
        (("0.1", "0.2"), "0.3"),
        (
            ("10000000000000000000000000001", "0.00000000000000000000000000001"),
            "10000000000000000000000000001.00000000000000000000000000001",
        ),
        (("0e-100000000", "10"), "10"),
        (("0", "0"), "0"),
    ],
)
def test_source_weight_totals_keep_all_significant_digits_without_fixed_precision(
    weights: tuple[str, str], total: str
) -> None:
    ((snapshot,),) = _snapshots(
        "local p=CreateItemPool() "
        + _add("I001", weights[0])
        + _add("I002", weights[1])
        + "PlaceRandomItem(p,0,0)"
    )
    assert snapshot.total_weight == total
    assert tuple(member.weight for member in snapshot.members) == weights


@pytest.mark.parametrize(
    "weight",
    ["udg_weight", "GetRandomReal(1,10)", "1+2", "-1", "1e100000000", "1e-100000000"],
)
def test_unresolved_or_unverifiable_weights_remain_verbatim(weight: str) -> None:
    ((snapshot,),) = _snapshots(
        "local p=CreateItemPool() " + _add("I001", weight) + "PlaceRandomItem(p,0,0)"
    )
    assert snapshot.members[0].weight == weight and snapshot.total_weight == ""
    assert snapshot.diagnostic


def test_removal_updates_active_members_but_keeps_full_operation_history() -> None:
    body = (
        "local p=CreateItemPool() "
        + _add("I001")
        + _add("I002", "30")
        + "ItemPoolRemoveItemType(p,FourCC('I001')) PlaceRandomItem(p,0,0)"
    )
    ((snapshot,),) = _snapshots(body)
    assert [member.code for member in snapshot.members] == ["I002"]
    assert snapshot.total_weight == "30" and len(snapshot.operations) == 3
    records = trigger_acquisitions(_trigger(body), lua=True)
    assert format_trigger_acquisitions(records, str, target="I001") == []
    assert format_trigger_acquisitions(records, str, target="I002")


def test_destroyed_pool_is_reported_without_an_active_reward() -> None:
    ((snapshot,),) = _snapshots(
        "local p=CreateItemPool() "
        + _add("I001")
        + "DestroyItemPool(p) PlaceRandomItem(p,0,0)"
    )
    assert (
        snapshot.destroyed and not snapshot.members and "已销毁" in snapshot.diagnostic
    )
    assert len(snapshot.operations) == 2


def test_rebuilding_a_pool_does_not_borrow_members_from_the_previous_instance() -> None:
    text = (
        "local p=CreateItemPool() "
        + _add("I001")
        + "PlaceRandomItem(p,0,0) p=CreateItemPool() "
        + _add("I002", "30")
        + "PlaceRandomItem(p,0,0)"
    )
    ((first,), (second,)) = _snapshots(text)
    assert [member.code for member in first.members] == ["I001"]
    assert [member.code for member in second.members] == ["I002"]
    assert first.origin != second.origin


def test_overwriting_pool_with_nil_does_not_restore_an_old_definition() -> None:
    ((snapshot,),) = _snapshots(
        "local p=CreateItemPool() " + _add("I001") + "p=nil PlaceRandomItem(p,0,0)"
    )
    assert not snapshot.members and snapshot.diagnostic and snapshot.total_weight == ""


def test_replacing_parent_table_does_not_reuse_old_pool_members() -> None:
    text = (
        "local pools={} pools[1]=CreateItemPool() "
        + _add("I001", pool="pools[1]")
        + "PlaceRandomItem(pools[1],0,0) pools={} "
        + _add("I002", pool="pools[1]")
        + "PlaceRandomItem(pools[1],0,0)"
    )
    ((first,), (second,)) = _snapshots(text)
    assert [member.code for member in first.members] == ["I001"]
    assert [member.code for member in second.members] == ["I002"] and second.diagnostic


def test_string_keys_keep_internal_spaces_and_array_instances_separate() -> None:
    text = (
        "local pools={} pools['a b']=CreateItemPool() pools['ab']=CreateItemPool() "
        + _add("I001", pool="pools['a b']")
        + _add("I002", pool="pools['ab']")
        + "PlaceRandomItem(pools[ 'a b' ],0,0) PlaceRandomItem(pools['ab'],0,0)"
    )
    ((first,), (second,)) = _snapshots(text)
    assert [member.code for member in first.members] == ["I001"]
    assert [member.code for member in second.members] == ["I002"]


def test_local_pools_in_sibling_functions_do_not_mix() -> None:
    text = (
        "function One() local p=CreateItemPool() "
        + _add("I001")
        + "PlaceRandomItem(p,0,0) end function Two() local p=CreateItemPool() "
        + _add("I002")
        + "PlaceRandomItem(p,0,0) end"
    )
    ((first,), (second,)) = _snapshots(text)
    assert [member.code for member in first.members] == ["I001"]
    assert [member.code for member in second.members] == ["I002"]


def test_closure_captures_original_local_when_another_local_reuses_its_name() -> None:
    text = (
        "function Init() local p=CreateItemPool() "
        + _add("I001")
        + "TriggerAddAction(t,function() PlaceRandomItem(p,0,0) end) local p=CreateItemPool() "
        + _add("I002")
        + "end"
    )
    ((snapshot,),) = _snapshots(text)
    assert [member.code for member in snapshot.members] == ["I001"]


def test_closure_with_reassigned_pool_keeps_separate_definition_candidates() -> None:
    text = (
        "function Init() local p=CreateItemPool() "
        + _add("I001")
        + "TriggerAddAction(t,function() PlaceRandomItem(p,0,0) end) p=CreateItemPool() "
        + _add("I002")
        + "end"
    )
    (snapshots,) = _snapshots(text)
    assert len(snapshots) == 2
    assert [[member.code for member in snapshot.members] for snapshot in snapshots] == [
        ["I001"],
        ["I002"],
    ]
    assert all("2个定义候选" in snapshot.diagnostic for snapshot in snapshots)


def test_global_definition_is_found_even_when_handler_is_declared_first() -> None:
    text = (
        "function Reward() PlaceRandomItem(p,0,0) end function Init() p=CreateItemPool() "
        + _add("I001")
        + "end"
    )
    ((snapshot,),) = _snapshots(text)
    assert snapshot.members[0].code == "I001" and snapshot.total_weight == "10"
    assert "跨函数" in snapshot.diagnostic


def test_function_pool_parameter_does_not_borrow_a_same_named_global() -> None:
    text = (
        "p=CreateItemPool() "
        + _add("I001")
        + "function Reward(p) PlaceRandomItem(p,0,0) end"
    )
    ((snapshot,),) = _snapshots(text)
    assert not snapshot.members and snapshot.diagnostic


@pytest.mark.parametrize(
    "assignment",
    [
        "local p=(CreateItemPool())",
        "local p=(((CreateItemPool())))",
        "local u,p=0,CreateItemPool()",
        "local p,q=CreateItemPool(),CreateItemPool()",
    ],
)
def test_parenthesized_and_multiple_assignment_pool_creations(assignment: str) -> None:
    ((snapshot,),) = _snapshots(
        assignment + " " + _add("I001") + "PlaceRandomItem(p,0,0)"
    )
    assert snapshot.origin >= 0 and snapshot.members[0].code == "I001"


def test_non_pool_expression_is_not_promoted_to_a_create_definition() -> None:
    ((snapshot,),) = _snapshots(
        "local p=CreateItemPool() or OtherPool() "
        + _add("I001")
        + "PlaceRandomItem(p,0,0)"
    )
    assert snapshot.origin < 0 and snapshot.total_weight == "" and snapshot.diagnostic


def test_table_fields_do_not_reassign_a_same_named_local_pool() -> None:
    ((snapshot,),) = _snapshots(
        "local p=CreateItemPool() "
        + _add("I001")
        + "local data={p=nil, nested={p=7}} PlaceRandomItem(p,0,0)"
    )
    assert snapshot.members[0].code == "I001" and snapshot.total_weight == "10"


@pytest.mark.parametrize(
    "mutation",
    [_add("I001"), "ItemPoolRemoveItemType(p,FourCC('I002'))", "DestroyItemPool(p)"],
)
def test_conditional_mutations_keep_candidates_and_do_not_invent_a_total(
    mutation: str,
) -> None:
    ((snapshot,),) = _snapshots(
        "local p=CreateItemPool() "
        + _add("I002", "30")
        + "if flag then "
        + mutation
        + " end PlaceRandomItem(p,0,0)"
    )
    assert "I002" in {member.code for member in snapshot.members}
    assert "条件/循环" in snapshot.diagnostic and snapshot.total_weight == ""


def test_conditional_recreation_keeps_old_and_new_pool_definitions_separate() -> None:
    text = (
        "local p=CreateItemPool() "
        + _add("I001")
        + "if flag then p=CreateItemPool() "
        + _add("I002")
        + "end PlaceRandomItem(p,0,0)"
    )
    (snapshots,) = _snapshots(text)
    assert len(snapshots) == 2
    assert [[member.code for member in snapshot.members] for snapshot in snapshots] == [
        ["I001"],
        ["I002"],
    ]


def test_loop_registration_is_not_mistaken_for_a_single_fixed_weight() -> None:
    ((snapshot,),) = _snapshots(
        "local p=CreateItemPool() for i=1,10 do "
        + _add("I001")
        + "end PlaceRandomItem(p,0,0)"
    )
    assert snapshot.members[0].code == "I001" and snapshot.total_weight == ""
    assert "循环" in snapshot.diagnostic


def test_lua_calls_named_after_jass_keywords_do_not_create_pool_control_scopes() -> (
    None
):
    ((snapshot,),) = _snapshots(
        "local p=CreateItemPool() loop() endif() endloop() "
        + _add("I001")
        + "PlaceRandomItem(p,0,0)"
    )
    assert snapshot.total_weight == "10"


def test_unknown_cross_function_mutation_order_is_diagnosed() -> None:
    text = (
        "function Init() p=CreateItemPool() "
        + _add("I001")
        + "end function Modify() ItemPoolRemoveItemType(p,FourCC('I001')) end function Reward() PlaceRandomItem(p,0,0) end"
    )
    ((snapshot,),) = _snapshots(text)
    assert snapshot.members[0].code == "I001" and snapshot.total_weight == ""
    assert "多个函数" in snapshot.diagnostic and len(snapshot.operations) == 2


def test_duplicate_item_registrations_are_not_silently_added_or_overwritten() -> None:
    ((snapshot,),) = _snapshots(
        "local p=CreateItemPool() "
        + _add("I001", "10")
        + _add("I001", "30")
        + "PlaceRandomItem(p,0,0)"
    )
    assert [member.weight for member in snapshot.members] == ["10", "30"]
    assert "重复登记" in snapshot.diagnostic and snapshot.total_weight == ""


def test_dynamic_id_and_dynamic_removal_remain_visible() -> None:
    text = (
        "local p=CreateItemPool() ItemPoolAddItemType(p,ChooseType(),10) "
        + _add("I001")
        + "ItemPoolRemoveItemType(p,udg_type) PlaceRandomItem(p,0,0)"
    )
    ((snapshot,),) = _snapshots(text)
    assert (
        len(snapshot.members) == 2
        and snapshot.members[0].item_expression == "ChooseType()"
    )
    assert snapshot.total_weight == "" and "动态" in snapshot.diagnostic


def test_zero_item_id_remains_in_the_source_weight_denominator() -> None:
    text = _trigger(
        "local p=CreateItemPool() ItemPoolAddItemType(p,0,10) "
        + _add("I001", "30")
        + "PlaceRandomItem(p,0,0)"
    )
    output = "\n".join(
        format_trigger_acquisitions(
            trigger_acquisitions(text, lua=True), str, target="I001"
        )
    )
    assert "空物品ID[0]" in output and "原文总权重: 40" in output
    assert "原文权重 30 / 40" in output


def test_mutations_after_a_placement_do_not_rewrite_the_earlier_snapshot() -> None:
    text = (
        "local p=CreateItemPool() "
        + _add("I001")
        + "PlaceRandomItem(p,0,0) "
        + _add("I002", "30")
        + "PlaceRandomItem(p,0,0)"
    )
    ((first,), (second,)) = _snapshots(text)
    assert [member.code for member in first.members] == [
        "I001"
    ] and first.total_weight == "10"
    assert [member.code for member in second.members] == [
        "I001",
        "I002",
    ] and second.total_weight == "40"


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
def test_guide_shows_every_pool_member_and_each_placement(
    section: str, event: str, condition: str
) -> None:
    body = (
        "local p=CreateItemPool() "
        + _add("I001")
        + _add("I002", "30")
        + "PlaceRandomItem(p,0,0) PlaceRandomItem(p,0,0)"
    )
    output = format_guide_report(_map(_trigger(body, event, condition)), section)
    assert output.count("成员: ") == 2
    assert output.count("原文: PlaceRandomItem(p,0,0)") == 2
    assert "原文总权重: 40" in output


def test_members_and_repeated_placements_have_no_display_ceiling_or_quadratic_catalog() -> (
    None
):
    count = 2200
    body = (
        "local p=CreateItemPool() "
        + " ".join(_add(f"I{index:03X}", "1") for index in range(count))
        + "PlaceRandomItem(p,0,0) " * count
    )
    records = trigger_acquisitions(_trigger(body), lua=True)
    assert len(records) == count
    assert all(record.pools[0] is records[0].pools[0] for record in records)
    assert len(records[0].pools[0].members) == count
    output = "\n".join(
        format_trigger_acquisitions(records, str, target=f"I{count - 1:03X}")
    )
    assert output.count("成员: ") == count
    assert output.count("原文: PlaceRandomItem(p,0,0)") == count
    assert len(output) < count * 700


def test_array_reference_nesting_has_no_parser_depth_ceiling() -> None:
    handle = "p[" + "a[" * 1200 + "0" + "]" * 1200 + "]"
    ((snapshot,),) = _snapshots(
        "local p={} "
        + handle
        + "=CreateItemPool() "
        + _add("I001", pool=handle)
        + f"PlaceRandomItem({handle},0,0)"
    )
    assert snapshot.members[0].code == "I001" and "动态索引" in snapshot.diagnostic


def test_comments_and_display_strings_do_not_register_pool_members() -> None:
    text = (
        "local p=CreateItemPool() -- "
        + _add("I002")
        + "\nBJDebugMsg([["
        + _add("I003")
        + "]]) "
        + _add("I001")
        + "PlaceRandomItem(p,0,0)"
    )
    ((snapshot,),) = _snapshots(text)
    assert [member.code for member in snapshot.members] == ["I001"]


@pytest.mark.parametrize("command", ["where", "drop"])
def test_source_pool_member_is_queryable_even_when_missing_from_object_tables(
    pack: Path, command: str
) -> None:
    text = _trigger(
        "local p=CreateItemPool() " + _add("I9FF") + "PlaceRandomItem(p,0,0)"
    )
    (pack / "脚本可读文本" / "war3map.lua").write_text(text, encoding="utf-8")
    result = queries.execute_pack_query(PackQueryCliOptions(str(pack), command, "I9FF"))
    assert result.exit_code == 0
    assert "成员: [I9FF]" in result.render() and "原文总权重: 10" in result.render()


def test_global_qualified_pool_apis_and_fourcc_keep_native_semantics() -> None:
    text = "_G.p=_G.CreateItemPool() _G.ItemPoolAddItemType(p,_G.FourCC('I001'),10) _G.PlaceRandomItem(_G.p,0,0)"
    ((snapshot,),) = _snapshots(text)
    assert snapshot.members[0].code == "I001" and snapshot.total_weight == "10"
