"""Readable, complete GUI object and report presentation."""

from __future__ import annotations

from tests.gui_base import GuiTestCase
from w3xtool.api import GameObject, MapData
from w3xtool.gui_reports import build_analysis_blocks, format_blocks
from w3xtool.item_relation_models import (
    ItemRelation,
    ItemRelationIndex,
    ItemRelationKind,
    RelationCompleteness,
    RelationConfidence,
    RelationEvidence,
    RelationObject,
)
from w3xtool.object_text_models import (
    ObjectTextIndex,
    ObjectTextRecord,
    ObjectTextState,
    TextSelectionReason,
    TextSourcePriority,
)
from w3xtool.wtg_models import TriggerHeader, TriggerTreeSummary


class ObjectPresentationTest(GuiTestCase):
    def test_object_detail_cleans_markup_groups_fields_and_keeps_sources(self) -> None:
        # Given: one extracted object mixes rich text, gameplay, resources and defaults.
        obj = GameObject(
            category="\u7269\u54c1",
            ext="w3t",
            obj_id="I001",
            base_id="ratf",
            name="|cffffcc00Flame Sword|r",
            is_custom=True,
            fields=[
                ("\u8bf4\u660e", "Damage +1|nCritical +5%"),
                ("\u51b7\u5374 (\u7b49\u7ea71)", "5"),
                ("\u56fe\u6807", "ReplaceableTextures\\CommandButtons\\BTNItem.blp"),
                ("\u4f5c\u7528\u8303\u56f4 (\u7b49\u7ea72)", "-"),
            ],
            icon="ReplaceableTextures\\CommandButtons\\BTNItem.blp",
            field_values={
                "display:description": "Damage +1|nCritical +5%",
                "Cool1": "5",
                "display:icon": "ReplaceableTextures\\CommandButtons\\BTNItem.blp",
                "Area2": "-",
            },
            field_sources={
                "display:description": "ItemStrings.txt",
                "Cool1": "war3map.w3t",
                "display:icon": "ItemData.slk",
                "Area2": "ItemData.slk",
            },
        )

        # When: the object detail panel renders the extracted model.
        self.app.map_data = MapData("fixture.w3x", "fixture")
        self.app._show_detail(obj)
        text = self.app.detail.get("1.0", "end")

        # Then: Warcraft markup is readable, fields are grouped, and evidence stays visible.
        assert self.app.detail_title.cget("text") == "Flame Sword"
        assert "Damage +1\nCritical +5%" in text
        assert "\u6218\u6597\u4e0e\u6570\u503c" in text
        assert "\u8d44\u6e90\u4e0e\u5916\u89c2" in text
        assert "\u672a\u8bbe\u7f6e/\u9ed8\u8ba4\u5b57\u6bb5" in text
        assert "\u6570\u636e\u6765\u6e90" in text
        assert "|cffffcc00" not in text
        assert "|n" not in text
        assert "【核心说明】" not in text

    def test_item_detail_keeps_complete_readable_and_raw_text(self) -> None:
        # Given: one item has a long, level-specific map text value.
        raw = "|cffffcc00" + ("原始全文|n" * 1200) + "|r"
        readable = "原始全文\n" * 1200
        md, item, _unit, _skill = _map_with_item_intelligence(raw, readable)

        # When: the item is shown in the real scrollable detail widget.
        self.app.map_data = md
        self.app._show_detail(item)
        text = self.app.detail.get("1.0", "end-1c")

        # Then: both representations and their exact evidence survive without slicing.
        assert "【完整文本：可读版】" in text
        assert "【完整文本：原始版】" in text
        assert readable in text
        assert raw in text
        assert "扩展说明｜等级 2｜地图原值" in text
        assert "war3map.w3t" in text
        assert "规范字段：ubertip" in text
        assert "证据优先级：600｜当前值：是" in text
        assert "选择原因：最高优先级唯一值" in text
        assert "……" not in text

    def test_item_detail_lists_acquisition_and_equipment_skills(self) -> None:
        # Given: one item is dropped by a unit and provides one ability.
        md, item, _unit, _skill = _map_with_item_intelligence("说明", "说明")

        # When: the item detail is rendered from immutable relation indexes.
        self.app.map_data = md
        self.app._show_detail(item)
        text = self.app.detail.get("1.0", "end-1c")

        # Then: acquisition, skill, probability, confidence, and evidence are visible.
        assert "【获取方式】" in text
        assert "怪物直接掉落" in text
        assert "掉落怪(n001)" in text
        assert "概率：75%" in text
        assert "【装备技能】" in text
        assert "烈焰技能(A001)" in text
        assert "【掉落/可获取装备】" not in text
        assert "可信度：已确认" in text
        assert "war3mapUnits.doo" in text
        assert "偏移 128" in text

    def test_unit_detail_lists_every_item_from_source_reverse_index(self) -> None:
        # Given: one unit is the retained source endpoint of an item drop.
        md, _item, unit, _skill = _map_with_item_intelligence("说明", "说明")

        # When: the source unit is opened.
        self.app.map_data = md
        self.app._show_detail(unit)
        text = self.app.detail.get("1.0", "end-1c")

        # Then: the unit-to-item reverse relation is available in its details.
        assert "【掉落/可获取装备】" in text
        assert "烈焰剑(I001)" in text

    def test_skill_detail_lists_every_item_from_skill_reverse_index(self) -> None:
        # Given: one skill is provided by an indexed equipment item.
        md, _item, _unit, skill = _map_with_item_intelligence("说明", "说明")

        # When: the skill object is opened.
        self.app.map_data = md
        self.app._show_detail(skill)
        text = self.app.detail.get("1.0", "end-1c")

        # Then: the skill-to-item reverse relation is available in its details.
        assert "【由哪些装备提供】" in text
        assert "烈焰剑(I001)" in text

    def test_copy_full_analysis_contains_every_trigger(self) -> None:
        # Given: more trigger headers than the old GUI summary limit.
        triggers = tuple(
            TriggerHeader(
                name=f"T{index:02d}",
                description="",
                is_comment=False,
                is_enabled=True,
                is_custom_text=False,
                is_initially_off=False,
                run_on_init=False,
                category_id=0,
                function_count=0,
            )
            for index in range(1, 11)
        )
        md = MapData("fixture.w3x", "fixture")
        md.trigger_summary = TriggerTreeSummary(
            version=7,
            is_reforged=False,
            category_count=0,
            variable_count=0,
            trigger_count=len(triggers),
            comment_count=0,
            script_count=0,
            categories=(),
            variables=(),
            triggers=triggers,
            eca_functions=(),
        )

        # When: the full analysis text used by the copy action is built.
        text = format_blocks(build_analysis_blocks(md))

        # Then: no extracted trigger disappears behind a preview-only slice.
        assert "T09" in text
        assert "T10" in text


def _map_with_item_intelligence(
    raw: str,
    readable: str,
) -> tuple[MapData, GameObject, GameObject, GameObject]:
    item = GameObject("物品", "w3t", "I001", "ratf", "烈焰剑", True)
    unit = GameObject("单位", "w3u", "n001", "n001", "掉落怪", True)
    skill = GameObject("技能", "w3a", "A001", "A001", "烈焰技能", True)
    md = MapData(
        "fixture.w3x",
        "fixture",
        objects={"物品": [item], "单位": [unit], "技能": [skill]},
    )
    md.object_texts = ObjectTextIndex.build(
        (
            ObjectTextRecord(
                category="物品",
                object_id="I001",
                base_id="ratf",
                object_name="烈焰剑",
                is_custom=True,
                role="扩展说明",
                semantic_field="ubertip",
                field_key="utub:2",
                field_label="扩展提示 - 等级 2",
                level=2,
                raw_value=raw,
                readable_value=readable,
                source_kind="地图二进制",
                source_path="war3map.w3t",
                source_priority=int(TextSourcePriority.MAP_BINARY),
                state=ObjectTextState.MAP_VALUE,
                placeholder=False,
                conflict_group="",
                is_current=True,
                selection_reason=TextSelectionReason.HIGHEST_PRIORITY_VALUE,
                evidence_ordinal=1,
            ),
        )
    )
    relation_item = RelationObject("物品", "I001", "烈焰剑")
    md.item_relations = ItemRelationIndex.build(
        (
            ItemRelation(
                kind=ItemRelationKind.UNIT_DROP,
                item=relation_item,
                source=RelationObject("单位", "n001", "掉落怪"),
                group_index=1,
                entry_index=2,
                chance=75,
                evidence=RelationEvidence(source="war3mapUnits.doo", offset=128),
                confidence=RelationConfidence.CONFIRMED,
                completeness=RelationCompleteness.COMPLETE,
            ),
            ItemRelation(
                kind=ItemRelationKind.ITEM_ABILITY,
                item=relation_item,
                skill=RelationObject("技能", "A001", "烈焰技能"),
                evidence=RelationEvidence(
                    source="war3map.w3t",
                    field_key="iabi",
                ),
                confidence=RelationConfidence.CONFIRMED,
                completeness=RelationCompleteness.COMPLETE,
            ),
        )
    )
    return md, item, unit, skill
