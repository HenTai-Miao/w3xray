"""Lossless acquisition, equipment-skill, and relation completeness reports."""

from __future__ import annotations

from collections import Counter
from typing import Final

from .batch_tsv import format_tsv_rows
from .item_relation_models import (
    ItemRelation,
    ItemRelationIndex,
    ItemRelationKind,
    RelationCompleteness,
    RelationConfidence,
)

_SKILL_KINDS: Final = frozenset(
    (ItemRelationKind.ITEM_ABILITY, ItemRelationKind.COOLDOWN_ABILITY)
)
_ACQUISITION_HEADER: Final = (
    "关系ID",
    "地图子图",
    "关系类型",
    "装备ID",
    "装备名称",
    "来源分类",
    "来源ID",
    "来源名称",
    "实例序号",
    "玩家",
    "X",
    "Y",
    "Z",
    "掉落组",
    "组内序号",
    "概率",
    "槽位",
    "合成材料ID",
    "合成材料名称与数量",
    "证据文件",
    "证据函数/触发",
    "证据行号/偏移",
    "原始证据",
    "可信度",
    "完整性",
    "未解析原因",
)
_SKILL_HEADER: Final = (
    "关系ID",
    "装备ID",
    "装备名称",
    "关系角色",
    "技能ID",
    "技能名称",
    "字段键",
    "字段来源",
    "可信度",
    "完整性",
    "未解析原因",
)


def format_item_acquisition_tsv(index: ItemRelationIndex) -> str:
    """Render all non-skill item acquisition relations in stable index order."""
    rows: list[tuple[str, ...]] = [_ACQUISITION_HEADER]
    rows.extend(
        _acquisition_row(relation)
        for relation in index.records
        if relation.kind not in _SKILL_KINDS
    )
    return format_tsv_rows(rows)


def format_equipment_skills_tsv(index: ItemRelationIndex) -> str:
    """Render item ability and shared-cooldown relations only."""
    rows: list[tuple[str, ...]] = [_SKILL_HEADER]
    rows.extend(
        _skill_row(relation)
        for relation in index.records
        if relation.kind in _SKILL_KINDS
    )
    return format_tsv_rows(rows)


def format_relation_completeness(index: ItemRelationIndex) -> str:
    """Summarize every closed relation state and explicit evidence gap."""
    kind_counts = Counter(relation.kind for relation in index.records)
    confidence_counts = Counter(relation.confidence for relation in index.records)
    completeness_counts = Counter(relation.completeness for relation in index.records)
    reason_counts = Counter(
        relation.unresolved_reason
        for relation in index.records
        if relation.unresolved_reason
    )
    unavailable_counts = Counter(
        reason for reason in reason_counts if "不可用" in reason
    )
    lines = [f"关系总数：{len(index.records)}"]
    lines.extend(
        f"关系类型：{kind.value}：{kind_counts[kind]}" for kind in ItemRelationKind
    )
    lines.extend(
        f"可信度：{confidence.value}：{confidence_counts[confidence]}"
        for confidence in RelationConfidence
    )
    lines.extend(
        f"完整性：{state.value}：{completeness_counts[state]}"
        for state in RelationCompleteness
    )
    if unavailable_counts:
        lines.extend(
            f"不可用通道：{reason}：{reason_counts[reason]}"
            for reason in sorted(unavailable_counts, key=str.casefold)
        )
    else:
        lines.append("不可用通道：无显式记录")
    lines.extend(
        f"未解析原因：{reason}：{count}"
        for reason, count in sorted(
            reason_counts.items(), key=lambda item: item[0].casefold()
        )
    )
    return "\n".join(lines) + "\n"


def _acquisition_row(relation: ItemRelation) -> tuple[str, ...]:
    source = relation.source
    evidence = relation.evidence
    return (
        relation.relation_id,
        relation.map_name,
        relation.kind.value,
        relation.item.object_id,
        relation.item.name,
        "" if source is None else source.category,
        "" if source is None else source.object_id,
        "" if source is None else source.name,
        _optional_int(relation.instance_serial),
        _optional_int(relation.player),
        _optional_float(relation.x),
        _optional_float(relation.y),
        _optional_float(relation.z),
        _optional_int(relation.group_index),
        _optional_int(relation.entry_index),
        _optional_int(relation.chance),
        _optional_int(relation.slot),
        ";".join(ingredient.item.object_id for ingredient in relation.ingredients),
        ";".join(
            f"{ingredient.item.name}×{ingredient.count}"
            for ingredient in relation.ingredients
        ),
        evidence.source,
        " / ".join(value for value in (evidence.function, evidence.trigger) if value),
        _evidence_position(relation),
        evidence.raw,
        relation.confidence.value,
        relation.completeness.value,
        relation.unresolved_reason,
    )


def _skill_row(relation: ItemRelation) -> tuple[str, ...]:
    skill = relation.skill
    return (
        relation.relation_id,
        relation.item.object_id,
        relation.item.name,
        relation.kind.value,
        "" if skill is None else skill.object_id,
        "" if skill is None else skill.name,
        relation.evidence.field_key,
        relation.evidence.source,
        relation.confidence.value,
        relation.completeness.value,
        relation.unresolved_reason,
    )


def _optional_int(value: int | None) -> str:
    return "" if value is None else str(value)


def _optional_float(value: float | None) -> str:
    return "" if value is None else repr(value)


def _evidence_position(relation: ItemRelation) -> str:
    evidence = relation.evidence
    parts: list[str] = []
    if evidence.line:
        parts.append(f"行 {evidence.line}")
    if evidence.offset:
        parts.append(f"偏移 {evidence.offset}")
    if evidence.location:
        parts.append(evidence.location)
    return " / ".join(parts)
