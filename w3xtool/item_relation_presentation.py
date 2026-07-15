"""Complete human-readable relation evidence for GUI surfaces."""

from __future__ import annotations

from typing import Final

from .item_relation_models import ItemRelation, ItemRelationKind, RelationObject
from .map_data import GameObject, MapData

_SKILL_KINDS: Final = frozenset(
    (ItemRelationKind.ITEM_ABILITY, ItemRelationKind.COOLDOWN_ABILITY)
)


def format_object_relation_sections(md: MapData, obj: GameObject) -> str:
    """Render item, source, and skill reverse relations for one object."""
    sections: list[str] = []
    item_rows = md.item_relations.for_item(obj.category, obj.obj_id)
    acquisitions = tuple(row for row in item_rows if row.kind not in _SKILL_KINDS)
    skills = tuple(row for row in item_rows if row.kind in _SKILL_KINDS)
    _append_section(sections, "获取方式", acquisitions)
    _append_section(sections, "装备技能", skills)
    _append_section(
        sections,
        "掉落/可获取装备",
        md.item_relations.for_source(obj.category, obj.obj_id),
    )
    _append_section(
        sections,
        "由哪些装备提供",
        md.item_relations.for_skill(obj.category, obj.obj_id),
    )
    return "" if not sections else "\n" + "\n\n".join(sections) + "\n"


def format_relation_evidence(relation: ItemRelation) -> str:
    """Render every retained relation attribute and its source evidence."""
    lines = [
        f"关系：{relation.kind.value}",
        f"装备：{_format_endpoint(relation.item)}",
        f"关系 ID：{relation.relation_id}",
    ]
    if relation.source is not None:
        lines.append(f"来源对象：{_format_endpoint(relation.source)}")
    if relation.skill is not None:
        lines.append(f"技能：{_format_endpoint(relation.skill)}")
    _append_context(lines, relation)
    lines.append(
        f"可信度：{relation.confidence.value}｜完整性：{relation.completeness.value}"
    )
    if relation.unresolved_reason:
        lines.append(f"未解析原因：{relation.unresolved_reason}")
    _append_evidence(lines, relation)
    return "\n".join(lines)


def _append_section(
    sections: list[str],
    title: str,
    relations: tuple[ItemRelation, ...],
) -> None:
    if not relations:
        return
    blocks = [f"【{title}】"]
    blocks.extend(format_relation_evidence(relation) for relation in relations)
    sections.append("\n\n".join(blocks))


def _append_context(lines: list[str], relation: ItemRelation) -> None:
    if relation.map_name:
        lines.append(f"地图子图：{relation.map_name}")
    if relation.instance_serial is not None:
        lines.append(f"实例序号：{relation.instance_serial}")
    if relation.player is not None:
        lines.append(f"玩家：{relation.player}")
    coordinates = tuple(
        f"{axis}={value!r}"
        for axis, value in (("X", relation.x), ("Y", relation.y), ("Z", relation.z))
        if value is not None
    )
    if coordinates:
        lines.append(f"坐标：{', '.join(coordinates)}")
    drop = tuple(
        value
        for value in (
            None if relation.group_index is None else f"掉落组：{relation.group_index}",
            None
            if relation.entry_index is None
            else f"组内序号：{relation.entry_index}",
            None if relation.chance is None else f"概率：{relation.chance}%",
            None if relation.slot is None else f"槽位：{relation.slot}",
        )
        if value is not None
    )
    if drop:
        lines.append("｜".join(drop))
    if relation.ingredients:
        lines.append(
            "合成材料："
            + "；".join(
                f"{_format_endpoint(ingredient.item)}×{ingredient.count}"
                for ingredient in relation.ingredients
            )
        )


def _append_evidence(lines: list[str], relation: ItemRelation) -> None:
    evidence = relation.evidence
    source_parts = tuple(
        value
        for value in (
            evidence.source,
            None if not evidence.field_key else f"字段 {evidence.field_key}",
            None if not evidence.function else f"函数 {evidence.function}",
            None if not evidence.trigger else f"触发 {evidence.trigger}",
        )
        if value
    )
    lines.append(f"证据：{'｜'.join(source_parts) if source_parts else '未记录'}")
    positions = tuple(
        value
        for value in (
            None if not evidence.line else f"行 {evidence.line}",
            None if not evidence.offset else f"偏移 {evidence.offset}",
            evidence.location or None,
        )
        if value
    )
    if positions:
        lines.append(f"证据位置：{'｜'.join(positions)}")
    if evidence.raw:
        lines.extend(("原始证据：", evidence.raw))


def _format_endpoint(endpoint: RelationObject) -> str:
    return (
        f"{endpoint.name}({endpoint.object_id})"
        if endpoint.name
        else endpoint.object_id
    )
