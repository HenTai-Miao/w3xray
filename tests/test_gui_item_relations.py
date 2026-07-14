"""Searchable item-relation workspace behavior."""

from __future__ import annotations

from tests.gui_base import GuiTestCase
from w3xtool.api import GameObject, MapData
from w3xtool.item_relation_models import (
    ItemRelation,
    ItemRelationIndex,
    ItemRelationKind,
    RelationCompleteness,
    RelationConfidence,
    RelationEvidence,
    RelationObject,
)


class ItemRelationGuiTest(GuiTestCase):
    def test_relation_tab_lists_every_row_and_search_does_not_mutate_index(
        self,
    ) -> None:
        # Given: three relation kinds share one immutable index.
        md = _map_with_relations()
        before = md.item_relations.records

        # When: the map renders and an item ID query is applied.
        self.app._render_map(md, [], [], None)
        assert len(self.app.item_relation_tree.get_children()) == 3
        self.app.item_relation_search.set("I002")
        self.app._refresh_item_relations()

        # Then: one visible row remains and the source index is untouched.
        assert len(self.app.item_relation_tree.get_children()) == 1
        assert md.item_relations.records == before

    def test_relation_filters_apply_kind_and_confidence_together(self) -> None:
        # Given: relations use distinct kinds and confidence levels.
        self.app._render_map(_map_with_relations(), [], [], None)

        # When: both closed filters select the equipment-skill clue.
        self.app.item_relation_kind.set(ItemRelationKind.ITEM_ABILITY.value)
        self.app.item_relation_confidence.set(RelationConfidence.CLUE.value)
        self.app._refresh_item_relations()

        # Then: only that exact relation remains visible.
        rows = self.app.item_relation_tree.get_children()
        assert len(rows) == 1
        assert (
            self.app.item_relation_rows[rows[0]].kind is ItemRelationKind.ITEM_ABILITY
        )

    def test_selected_relation_shows_complete_evidence(self) -> None:
        # Given: a direct drop retains probability and binary offset evidence.
        self.app._render_map(_map_with_relations(), [], [], None)
        iid = _iid_for_kind(self.app, ItemRelationKind.UNIT_DROP)

        # When: the relation is selected for inspection.
        self.app.item_relation_tree.selection_set(iid)
        self.app._show_relation_evidence()
        text = self.app.item_relation_detail.get("1.0", "end-1c")

        # Then: the evidence view is complete and remains read-only.
        assert "war3mapUnits.doo" in text
        assert "偏移 128" in text
        assert "概率：75%" in text
        assert "可信度：已确认" in text
        assert self.app.item_relation_detail._textbox.cget("state") == "disabled"
        assert self.app.item_relation_tree.bind("<Double-1>")

    def test_target_button_opens_item_object_detail(self) -> None:
        # Given: a selected drop resolves to an extracted target item.
        self.app._render_map(_map_with_relations(), [], [], None)
        iid = _iid_for_kind(self.app, ItemRelationKind.UNIT_DROP)
        self.app.item_relation_tree.selection_set(iid)
        self.app._show_relation_evidence()

        # When: the target navigation action runs.
        self.app._open_relation_target()

        # Then: the object editor opens the exact item.
        assert self.app.tabs.get() == "对象编辑器"
        assert self.app.detail_title.cget("text") == "烈焰剑"

    def test_source_button_opens_source_object_detail(self) -> None:
        # Given: a selected drop resolves to an extracted source unit.
        self.app._render_map(_map_with_relations(), [], [], None)
        iid = _iid_for_kind(self.app, ItemRelationKind.UNIT_DROP)
        self.app.item_relation_tree.selection_set(iid)
        self.app._show_relation_evidence()

        # When: the source navigation action runs.
        self.app._open_relation_source()

        # Then: the object editor opens the exact source unit.
        assert self.app.tabs.get() == "对象编辑器"
        assert self.app.detail_title.cget("text") == "掉落怪"

    def test_unresolved_endpoints_disable_navigation_buttons(self) -> None:
        # Given: static evidence names an item that the object index cannot resolve.
        relation = ItemRelation(
            kind=ItemRelationKind.SCRIPT_REWARD,
            item=RelationObject("物品", "I404", "未解析"),
            evidence=RelationEvidence(source="war3map.j", line=18),
            confidence=RelationConfidence.CLUE,
            completeness=RelationCompleteness.UNRESOLVED,
            unresolved_reason="物品 I404 未解析",
        )
        md = MapData("fixture.w3x", "fixture")
        md.item_relations = ItemRelationIndex.build((relation,))
        self.app._render_map(md, [], [], None)

        # When: the unresolved row is selected.
        iid = self.app.item_relation_tree.get_children()[0]
        self.app.item_relation_tree.selection_set(iid)
        self.app._show_relation_evidence()

        # Then: neither action offers a dead navigation path.
        assert self.app.item_relation_target_button.cget("state") == "disabled"
        assert self.app.item_relation_source_button.cget("state") == "disabled"

    def test_filtering_out_selection_disables_stale_navigation(self) -> None:
        # Given: one resolved relation is selected and both navigation paths are active.
        self.app._render_map(_map_with_relations(), [], [], None)
        iid = _iid_for_kind(self.app, ItemRelationKind.UNIT_DROP)
        self.app.item_relation_tree.selection_set(iid)
        self.app._show_relation_evidence()
        assert self.app.item_relation_target_button.cget("state") == "normal"

        # When: filtering removes the selected row.
        self.app.item_relation_search.set("不存在的关系")
        self.app._refresh_item_relations()

        # Then: stale navigation actions are disabled with the empty evidence view.
        assert self.app.item_relation_target_button.cget("state") == "disabled"
        assert self.app.item_relation_source_button.cget("state") == "disabled"


def _map_with_relations() -> MapData:
    item_one = GameObject("物品", "w3t", "I001", "ratf", "烈焰剑", True)
    item_two = GameObject("物品", "w3t", "I002", "ratc", "寒冰甲", True)
    dropper = GameObject("单位", "w3u", "n001", "n001", "掉落怪", True)
    shop = GameObject("单位", "w3u", "n002", "n002", "商店", True)
    skill = GameObject("技能", "w3a", "A001", "A001", "烈焰技能", True)
    md = MapData(
        "fixture.w3x",
        "关系图",
        objects={
            "物品": [item_one, item_two],
            "单位": [dropper, shop],
            "技能": [skill],
        },
    )
    md.obj_index = {
        obj.obj_id: obj for obj in (item_one, item_two, dropper, shop, skill)
    }
    md.item_relations = ItemRelationIndex.build(
        (
            ItemRelation(
                kind=ItemRelationKind.UNIT_DROP,
                item=RelationObject("物品", "I001", "烈焰剑"),
                source=RelationObject("单位", "n001", "掉落怪"),
                group_index=0,
                entry_index=1,
                chance=75,
                evidence=RelationEvidence(source="war3mapUnits.doo", offset=128),
                confidence=RelationConfidence.CONFIRMED,
                completeness=RelationCompleteness.COMPLETE,
            ),
            ItemRelation(
                kind=ItemRelationKind.SHOP_SELL,
                item=RelationObject("物品", "I002", "寒冰甲"),
                source=RelationObject("单位", "n002", "商店"),
                player=2,
                x=512.0,
                y=-256.0,
                evidence=RelationEvidence(source="war3map.w3u", field_key="usei"),
                confidence=RelationConfidence.INFERRED,
                completeness=RelationCompleteness.COMPLETE,
            ),
            ItemRelation(
                kind=ItemRelationKind.ITEM_ABILITY,
                item=RelationObject("物品", "I001", "烈焰剑"),
                skill=RelationObject("技能", "A001", "烈焰技能"),
                evidence=RelationEvidence(source="war3map.w3t", field_key="iabi"),
                confidence=RelationConfidence.CLUE,
                completeness=RelationCompleteness.PARTIAL,
            ),
        )
    )
    return md


def _iid_for_kind(app, kind: ItemRelationKind) -> str:
    return next(
        iid for iid, relation in app.item_relation_rows.items() if relation.kind is kind
    )
