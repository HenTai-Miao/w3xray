"""Knowledge-pack publication tests for complete text and item relations."""

from __future__ import annotations

import csv
from pathlib import Path

from w3xtool.item_relation_models import (
    ItemRelation,
    ItemRelationIndex,
    ItemRelationKind,
    RelationCompleteness,
    RelationConfidence,
    RelationEvidence,
    RelationObject,
)
from w3xtool.knowledge_pack import write_knowledge_pack
from w3xtool.map_data import MapData
from w3xtool.object_text_models import (
    ObjectTextIndex,
    ObjectTextRecord,
    ObjectTextState,
    TextSelectionReason,
    TextSourcePriority,
)


def test_pack_writes_complete_text_and_all_relation_artifacts(tmp_path: Path) -> None:
    # Given: one map has lossless text, acquisition, and equipment-skill evidence.
    raw = '|cffffcc00"完整\t说明\r\n第二行|r'
    md = _map_with_text_and_relations(raw)

    # When: the normal knowledge pack is published.
    write_knowledge_pack(md, str(tmp_path))

    # Then: all dedicated artifacts exist and raw text round-trips exactly.
    expected = {
        "对象完整描述.tsv",
        "掉落与获取关系.tsv",
        "装备技能关系.tsv",
        "关系完整性.txt",
    }
    assert expected <= {path.name for path in tmp_path.iterdir()}
    with (tmp_path / "对象完整描述.tsv").open(
        encoding="utf-8",
        newline="",
    ) as handle:
        text_row = next(csv.DictReader(handle, delimiter="\t"))
    assert text_row["原始全文"] == raw
    assert "I001" in (tmp_path / "掉落与获取关系.tsv").read_text(encoding="utf-8")
    assert "A001" in (tmp_path / "装备技能关系.tsv").read_text(encoding="utf-8")


def test_manifest_coverage_and_audit_point_to_relation_indexes(tmp_path: Path) -> None:
    # Given: a complete map index can satisfy the static relationship requirement.
    md = _map_with_text_and_relations("完整说明")

    # When: the pack metadata is generated from those indexes.
    write_knowledge_pack(md, str(tmp_path))
    manifest = (tmp_path / "资料包目录.tsv").read_text(encoding="utf-8")
    coverage = (tmp_path / "需求覆盖.tsv").read_text(encoding="utf-8")
    audit = (tmp_path / "资料包审计.txt").read_text(encoding="utf-8")

    # Then: discovery and measured counts name the same durable artifacts.
    assert "装备关系\t掉落与获取关系.tsv" in manifest
    assert "对象\t对象完整描述.tsv" in manifest
    assert "分析装备掉落与获取\t已覆盖（静态证据）\t掉落与获取关系.tsv" in coverage
    assert "提取完整对象说明\t已覆盖（逐字段证据）\t对象完整描述.tsv" in coverage
    assert "对象完整文本\t总数 1\t地图原值 1" in audit
    assert "装备关系\t总数 2\t已确认 2" in audit


def test_relation_coverage_is_empty_or_partial_from_index_state(tmp_path: Path) -> None:
    # Given: one empty map and one relation map with unresolved static evidence.
    empty_dir = tmp_path / "empty"
    partial_dir = tmp_path / "partial"
    write_knowledge_pack(MapData("empty.w3x", "空图"), str(empty_dir))
    md = _map_with_text_and_relations("缺失")
    unresolved = ItemRelation(
        kind=ItemRelationKind.SCRIPT_REWARD,
        item=RelationObject("物品", "I404", "未解析"),
        evidence=RelationEvidence(source="war3map.j", line=8),
        confidence=RelationConfidence.CLUE,
        completeness=RelationCompleteness.UNRESOLVED,
        unresolved_reason="物品 I404 未解析",
    )
    md.item_relations = ItemRelationIndex.build(
        (*md.item_relations.records, unresolved)
    )

    # When: dynamic coverage evaluates both maps.
    write_knowledge_pack(md, str(partial_dir))
    empty = (empty_dir / "需求覆盖.tsv").read_text(encoding="utf-8")
    partial = (partial_dir / "需求覆盖.tsv").read_text(encoding="utf-8")

    # Then: no data is not overclaimed, and unresolved evidence stays partial.
    assert "分析装备掉落与获取\t未发现数据" in empty
    assert "提取完整对象说明\t未发现数据" in empty
    assert "分析装备掉落与获取\t部分覆盖" in partial


def _map_with_text_and_relations(raw: str) -> MapData:
    md = MapData("fixture.w3x", "关系图")
    md.object_texts = ObjectTextIndex.build(
        (
            ObjectTextRecord(
                category="物品",
                object_id="I001",
                base_id="ratf",
                object_name="装备",
                is_custom=True,
                role="扩展提示",
                semantic_field="ubertip",
                field_key="utub",
                field_label="提示文本",
                level=None,
                raw_value=raw,
                readable_value="完整说明\n第二行",
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
    item = RelationObject("物品", "I001", "装备")
    md.item_relations = ItemRelationIndex.build(
        (
            ItemRelation(
                kind=ItemRelationKind.UNIT_DROP,
                item=item,
                source=RelationObject("单位", "n001", "怪物"),
                group_index=0,
                entry_index=0,
                chance=100,
                evidence=RelationEvidence(source="war3mapUnits.doo", offset=64),
                confidence=RelationConfidence.CONFIRMED,
                completeness=RelationCompleteness.COMPLETE,
            ),
            ItemRelation(
                kind=ItemRelationKind.ITEM_ABILITY,
                item=item,
                skill=RelationObject("技能", "A001", "技能"),
                evidence=RelationEvidence(source="war3map.w3t", field_key="iabi"),
                confidence=RelationConfidence.CONFIRMED,
                completeness=RelationCompleteness.COMPLETE,
            ),
        )
    )
    return md
