"""Lossless complete-text presentation for object details."""

from __future__ import annotations

from enum import StrEnum

from .map_data import GameObject, MapData
from .object_text_models import ObjectTextRecord


class ObjectTextView(StrEnum):
    """The two lossless evidence scopes selectable in object detail."""

    CURRENT = "当前文本"
    ALL = "全部证据"


def records_for_text_view(
    records: tuple[ObjectTextRecord, ...],
    view: ObjectTextView,
) -> tuple[ObjectTextRecord, ...]:
    """Keep every current record or every retained source record."""
    return (
        records
        if view is ObjectTextView.ALL
        else tuple(row for row in records if row.is_current)
    )


def format_complete_text_section(
    md: MapData,
    obj: GameObject,
    view: ObjectTextView = ObjectTextView.ALL,
) -> str:
    """Render every readable and raw text record without truncation."""
    records = records_for_text_view(
        md.object_texts.for_object(obj.category, obj.obj_id), view
    )
    if not records:
        return "\n【完整文本】\n（未发现该对象的逐字段文本证据）\n"
    readable = _format_text_view("可读版", records, raw=False)
    differing = tuple(
        record for record in records if record.raw_value != record.readable_value
    )
    if differing:
        omitted = len(records) - len(differing)
        suffix = f"\n（另有 {omitted} 条原始文本与可读版逐字相同，已略）" if omitted else ""
        raw = _format_text_view("原始版", differing, raw=True) + suffix
    else:
        raw = "【完整文本：原始版】\n（原始版与可读版逐字相同，已略）"
    return f"\n{readable}\n{raw}\n"


def _merge_identical_records(
    records: tuple[ObjectTextRecord, ...],
) -> tuple[tuple[ObjectTextRecord, ...], ...]:
    """Fold adjacent records whose content and provenance are identical.

    地图作者常把同一段文字同时写进多个字段（如 utub 与 ides）；
    相邻且元数据一致时合并成一块，字段与证据序号聚合展示，不丢证据。
    """
    def _merge_key(record: ObjectTextRecord) -> tuple[object, ...]:
        return (
            record.level,
            record.state,
            record.source_kind,
            record.source_path,
            record.source_priority,
            record.is_current,
            record.selection_reason,
            record.placeholder,
            record.conflict_group,
            record.raw_value,
            record.readable_value,
        )

    groups: list[list[ObjectTextRecord]] = []
    previous_key: tuple[object, ...] | None = None
    for record in records:
        key = _merge_key(record)
        if key != previous_key or not groups:
            groups.append([record])
            previous_key = key
        else:
            groups[-1].append(record)
    return tuple(tuple(group) for group in groups)


def _format_text_view(
    label: str,
    records: tuple[ObjectTextRecord, ...],
    *,
    raw: bool,
) -> str:
    blocks = [f"【完整文本：{label}】"]
    for group in _merge_identical_records(records):
        blocks.append(_format_text_record(group, raw=raw))
    return "\n\n".join(blocks)


def _format_text_record(
    records: tuple[ObjectTextRecord, ...],
    *,
    raw: bool,
) -> str:
    first = records[0]
    level = "通用" if first.level is None else f"等级 {first.level}"
    source = (
        " · ".join(value for value in (first.source_kind, first.source_path) if value)
        or "未记录"
    )
    role = " + ".join(record.role for record in records)
    semantic_fields = "、".join(record.semantic_field for record in records)
    field_descriptions = "、".join(
        f"{record.field_label or '未命名'}（{record.field_key or '无字段键'}）"
        for record in records
    )
    ordinals = "、".join(str(record.evidence_ordinal) for record in records)
    lines = [
        f"── {role}｜{level}｜{first.state.value} ──",
        f"规范字段：{semantic_fields}",
        f"字段：{field_descriptions}",
        f"来源：{source}",
        f"证据优先级：{first.source_priority}｜当前值：{'是' if first.is_current else '否'}",
        f"选择原因：{first.selection_reason.value}",
        f"证据序号：{ordinals}",
    ]
    if first.conflict_group:
        lines.append(f"冲突组：{first.conflict_group}")
    if first.placeholder:
        lines.append("占位状态：是")
    value = first.raw_value if raw else first.readable_value
    lines.extend(("正文：", value if value else "（空文本）"))
    return "\n".join(lines)
