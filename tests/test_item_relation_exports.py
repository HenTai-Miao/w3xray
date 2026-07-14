"""Lossless complete-text and item-relation export tests."""

from __future__ import annotations

import csv
import io

from w3xtool.item_relation_exports import (
    format_equipment_skills_tsv,
    format_item_acquisition_tsv,
    format_relation_completeness,
)
from w3xtool.item_relation_models import (
    ItemRelation,
    ItemRelationIndex,
    ItemRelationKind,
    RelationCompleteness,
    RelationConfidence,
    RelationEvidence,
    RelationIngredient,
    RelationObject,
)
from w3xtool.object_text_exports import (
    format_object_text_completeness,
    format_object_text_tsv,
)
from w3xtool.object_text_models import (
    ObjectTextIndex,
    ObjectTextRecord,
    ObjectTextState,
)


def test_complete_text_tsv_round_trips_all_raw_characters_and_long_values() -> None:
    # Given: raw map text contains every character that needs TSV quoting.
    raw = '"开头\t字段\r\n' + ("长文本|n\n" * 2000)
    index = ObjectTextIndex.build((_text_record(raw),))

    # When: the complete evidence table is serialized and parsed normally.
    rows = list(csv.reader(io.StringIO(format_object_text_tsv(index)), delimiter="\t"))

    # Then: the fixed schema and original value round-trip byte-for-character.
    assert rows[0] == [
        "分类",
        "对象ID",
        "基础ID",
        "名称",
        "自定义",
        "文本角色",
        "字段键",
        "字段标签",
        "等级/变体",
        "原始全文",
        "可读全文",
        "来源类型",
        "来源路径",
        "状态",
        "占位",
        "冲突组",
        "证据序号",
    ]
    assert rows[1][9] == raw
    assert rows[1][10] == "可读\n全文"


def test_complete_text_summary_lists_all_seven_states_in_enum_order() -> None:
    # Given: only one state currently has a row.
    index = ObjectTextIndex.build((_text_record("正文"),))

    # When: completeness is formatted.
    lines = format_object_text_completeness(index).splitlines()

    # Then: absent states remain explicit and declaration order is stable.
    assert lines == [
        f"{state.value}：{int(state is ObjectTextState.MAP_VALUE)}"
        for state in ObjectTextState
    ]


def test_relation_exports_split_acquisition_and_equipment_skill_rows() -> None:
    # Given: one acquisition relation and one equipment-skill relation coexist.
    index = ItemRelationIndex.build((_drop_relation(), _item_ability_relation()))

    # When: dedicated reports are serialized.
    acquisition = list(
        csv.reader(io.StringIO(format_item_acquisition_tsv(index)), delimiter="\t")
    )
    skills = list(
        csv.reader(io.StringIO(format_equipment_skills_tsv(index)), delimiter="\t")
    )

    # Then: each report contains only its own relation family and evidence columns.
    assert [row[2] for row in acquisition[1:]] == ["怪物直接掉落"]
    assert [row[3] for row in skills[1:]] == ["装备技能"]
    assert "证据行号/偏移" in acquisition[0]
    assert "未解析原因" in acquisition[0]
    assert skills[1][4:6] == ["A001", "装备技能"]


def test_acquisition_export_keeps_coordinates_groups_materials_and_evidence() -> None:
    # Given: a recipe carries counted materials, coordinates, and line/offset evidence.
    item = RelationObject("物品", "I999", "成品")
    material = RelationObject("物品", "I001", "材料")
    relation = ItemRelation(
        kind=ItemRelationKind.RECIPE,
        item=item,
        source=RelationObject("单位", "n001", "锻造商"),
        ingredients=(RelationIngredient(material, 2),),
        instance_serial=7,
        player=1,
        x=1.25,
        y=-0.0,
        z=3.5,
        group_index=2,
        entry_index=3,
        chance=45,
        slot=4,
        evidence=RelationEvidence(
            source="war3map.j",
            function="Forge",
            trigger="锻造触发",
            line=9,
            offset=27,
            raw='call AddItem("I999")\n第二行\t证据',
        ),
        confidence=RelationConfidence.CONFIRMED,
        completeness=RelationCompleteness.COMPLETE,
    )

    # When: the acquisition report is parsed through the standard reader.
    rows = list(
        csv.DictReader(
            io.StringIO(
                format_item_acquisition_tsv(ItemRelationIndex.build((relation,)))
            ),
            delimiter="\t",
        )
    )

    # Then: structured and raw evidence are independently recoverable.
    assert rows[0]["合成材料ID"] == "I001"
    assert rows[0]["合成材料名称与数量"] == "材料×2"
    assert rows[0]["X"] == "1.25"
    assert rows[0]["Y"] == "-0.0"
    assert rows[0]["证据函数/触发"] == "Forge / 锻造触发"
    assert rows[0]["证据行号/偏移"] == "行 9 / 偏移 27"
    assert rows[0]["原始证据"] == 'call AddItem("I999")\n第二行\t证据'


def test_relation_summary_lists_zero_counts_and_unresolved_reasons() -> None:
    # Given: a partial clue carries an explicit unresolved reason.
    relation = ItemRelation(
        kind=ItemRelationKind.SCRIPT_REWARD,
        item=RelationObject("物品", "I404", "未解析"),
        evidence=RelationEvidence(source="war3map.lua", line=18),
        confidence=RelationConfidence.CLUE,
        completeness=RelationCompleteness.UNRESOLVED,
        unresolved_reason="物品 I404 未解析",
    )

    # When: the completeness report is formatted.
    report = format_relation_completeness(ItemRelationIndex.build((relation,)))

    # Then: all closed enums, the missing channel section, and reasons are visible.
    assert "关系类型：怪物直接掉落：0" in report
    assert "可信度：仅线索：1" in report
    assert "完整性：未解析：1" in report
    assert "不可用通道：无显式记录" in report
    assert "未解析原因：物品 I404 未解析：1" in report


def _text_record(raw: str) -> ObjectTextRecord:
    return ObjectTextRecord(
        category="物品",
        object_id="I001",
        base_id="ratf",
        object_name="戒指",
        is_custom=True,
        role="扩展提示",
        field_key="utub:2",
        field_label="提示文本 - 等级 2",
        level=2,
        raw_value=raw,
        readable_value="可读\n全文",
        source_kind="地图二进制",
        source_path="war3map.w3t",
        state=ObjectTextState.MAP_VALUE,
        placeholder=False,
        conflict_group="",
        evidence_ordinal=1,
    )


def _drop_relation() -> ItemRelation:
    return ItemRelation(
        kind=ItemRelationKind.UNIT_DROP,
        item=RelationObject("物品", "I001", "掉落装备"),
        source=RelationObject("单位", "n001", "掉落怪"),
        group_index=0,
        entry_index=1,
        chance=75,
        evidence=RelationEvidence(source="war3mapUnits.doo", offset=128),
        confidence=RelationConfidence.CONFIRMED,
        completeness=RelationCompleteness.COMPLETE,
    )


def _item_ability_relation() -> ItemRelation:
    return ItemRelation(
        kind=ItemRelationKind.ITEM_ABILITY,
        item=RelationObject("物品", "I001", "掉落装备"),
        skill=RelationObject("技能", "A001", "装备技能"),
        evidence=RelationEvidence(source="war3map.w3t", field_key="iabi"),
        confidence=RelationConfidence.CONFIRMED,
        completeness=RelationCompleteness.COMPLETE,
    )
