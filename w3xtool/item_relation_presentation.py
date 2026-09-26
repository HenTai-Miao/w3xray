"""Complete human-readable relation evidence for GUI surfaces."""

from __future__ import annotations

from textwrap import indent
from typing import Final

from .item_relation_models import (
    ItemRelation,
    ItemRelationKind,
    RelationCompleteness,
    RelationConfidence,
    RelationObject,
)
from .map_data import GameObject, MapData
from .textobj import clean_text

_SKILL_KINDS: Final = frozenset(
    (ItemRelationKind.ITEM_ABILITY, ItemRelationKind.COOLDOWN_ABILITY)
)
_COMPACT_RAW_LIMIT: Final = 100


def format_object_relation_sections(
    md: MapData,
    obj: GameObject,
    detailed: bool = True,
) -> str:
    """Render compact item, source, and skill reverse relations for one object.

    ``detailed=False``（当前信息模式）只保留结论行与位置/概率上下文，
    证据行与原始证据留给完整证据模式。
    """
    sections: list[str] = []
    item_rows = md.item_relations.for_item(obj.category, obj.obj_id)
    acquisitions = tuple(row for row in item_rows if row.kind not in _SKILL_KINDS)
    skills = tuple(row for row in item_rows if row.kind in _SKILL_KINDS)
    _append_section(sections, "获取方式", acquisitions, obj, detailed)
    _append_section(sections, "装备技能", skills, obj, detailed)
    _append_section(
        sections,
        "掉落/可获取装备",
        md.item_relations.for_source(obj.category, obj.obj_id),
        obj,
        detailed,
    )
    _append_section(
        sections,
        "由哪些装备提供",
        md.item_relations.for_skill(obj.category, obj.obj_id),
        obj,
        detailed,
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
    anchor: GameObject,
    detailed: bool,
) -> None:
    if not relations:
        return
    blocks = [f"【{title}】"]
    for group in _merge_shared_evidence(relations):
        blocks.append(_format_compact_relations(group, anchor, detailed))
    sections.append("\n".join(blocks))


def _format_compact_relations(
    group: tuple[ItemRelation, ...],
    anchor: GameObject,
    detailed: bool,
) -> str:
    """One bullet per shared-evidence group for the object detail pane.

    对象自己的端点（“装备：翡翠指环(I02T)”）、SHA-256 关系 ID、默认的
    “已确认｜完整”结论都省略；完整哈希与全量证据仍由
    format_relation_evidence 和导出报告承载。当前信息模式再省去证据行。
    """
    first = group[0]
    head = f"· {first.kind.value}" + (f"（{len(group)} 条）" if len(group) > 1 else "")
    endpoints = _foreign_endpoints(group, anchor)
    if endpoints:
        head += "：" + "、".join(endpoints)
    lines = [head]
    context = _compact_context(first)
    if context:
        lines.append(f"  {context}")
    if detailed:
        lines.append(f"  {_compact_evidence(first)}")
    if first.ingredients:
        lines.append(
            "  合成材料："
            + "；".join(
                f"{_format_endpoint(ingredient.item)}×{ingredient.count}"
                for ingredient in first.ingredients
            )
        )
    if first.unresolved_reason:
        lines.append(f"  未解析原因：{first.unresolved_reason}")
    if (
        first.confidence is not RelationConfidence.CONFIRMED
        or first.completeness is not RelationCompleteness.COMPLETE
    ):
        lines.append(
            f"  可信度：{first.confidence.value}｜完整性：{first.completeness.value}"
        )
    return "\n".join(lines)


def _foreign_endpoints(
    group: tuple[ItemRelation, ...],
    anchor: GameObject,
) -> list[str]:
    """List endpoints unlike the anchor object, deduplicated and ordered."""

    def _is_self(endpoint: RelationObject) -> bool:
        return (
            endpoint.category == anchor.category and endpoint.object_id == anchor.obj_id
        )

    shown: list[str] = []

    def _add(endpoint: RelationObject | None) -> None:
        if endpoint is None or _is_self(endpoint):
            return
        text = _format_endpoint(endpoint)
        if text not in shown:
            shown.append(text)

    first = group[0]
    _add(first.source)
    for relation in group:
        _add(relation.skill)
    _add(first.item)
    return shown


def _compact_context(relation: ItemRelation) -> str:
    parts = [f"地图子图：{relation.map_name}"] if relation.map_name else []
    if relation.instance_serial is not None:
        parts.append(f"实例 {relation.instance_serial}")
    if relation.player is not None:
        parts.append(f"玩家 {relation.player}")
    parts.extend(
        f"{axis}={value!r}"
        for axis, value in (("X", relation.x), ("Y", relation.y), ("Z", relation.z))
        if value is not None
    )
    parts.extend(
        value
        for value in (
            None if relation.group_index is None else f"掉落组 {relation.group_index}",
            None
            if relation.entry_index is None
            else f"组内序号 {relation.entry_index}",
            None if relation.chance is None else f"概率 {relation.chance}%",
            None if relation.slot is None else f"槽位 {relation.slot}",
        )
        if value is not None
    )
    return " ｜ ".join(parts)


def _compact_evidence(relation: ItemRelation) -> str:
    evidence = relation.evidence
    parts = [
        value
        for value in (
            evidence.source,
            f"字段 {evidence.field_key}" if evidence.field_key else "",
            f"函数 {evidence.function}" if evidence.function else "",
            f"触发 {evidence.trigger}" if evidence.trigger else "",
        )
        if value
    ]
    # location 常与 field_key 同值（如 SLK 列名），去重避免"字段 x｜位置：x"。
    location = evidence.location or ""
    positions = [
        value
        for value in (
            f"行 {evidence.line}" if evidence.line else "",
            f"偏移 {evidence.offset}" if evidence.offset else "",
            location if location and location != evidence.field_key else "",
        )
        if value
    ]
    if positions:
        parts.append("位置：" + "｜".join(positions))
    if not parts:
        parts.append("未记录")
    line = "证据：" + "｜".join(parts)
    raw = evidence.raw
    if not raw:
        return line
    if "\n" in raw or len(raw) > _COMPACT_RAW_LIMIT:
        return line + "\n  原始证据：\n" + indent(raw, "    ")
    return line + f"｜原文 {raw}"


def _merge_shared_evidence(
    relations: tuple[ItemRelation, ...],
) -> tuple[tuple[ItemRelation, ...], ...]:
    """Fold adjacent relations that differ only in skill endpoint and ID.

    一个多码字段（如 iabi="A0TU,A089,AIt9"）会拆出多条关系，每条携带
    同一份整字段证据；相邻且上下文/证据一致时合并成一块，端点聚合展示。
    """

    def _merge_key(relation: ItemRelation) -> tuple[object, ...]:
        return (
            relation.kind,
            relation.item,
            relation.source,
            relation.map_name,
            relation.instance_serial,
            relation.player,
            relation.x,
            relation.y,
            relation.z,
            relation.slot,
            relation.group_index,
            relation.entry_index,
            relation.chance,
            relation.ingredients,
            relation.confidence,
            relation.completeness,
            relation.unresolved_reason,
            relation.evidence,
        )

    groups: list[list[ItemRelation]] = []
    previous_key: tuple[object, ...] | None = None
    for relation in relations:
        key = _merge_key(relation)
        if key != previous_key or not groups:
            groups.append([relation])
            previous_key = key
        else:
            groups[-1].append(relation)
    return tuple(tuple(group) for group in groups)


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
    """Readable endpoint label; Warcraft color codes never reach GUI text."""
    name = clean_text(endpoint.name).replace("\n", " ")
    return f"{name}({endpoint.object_id})" if name else endpoint.object_id
