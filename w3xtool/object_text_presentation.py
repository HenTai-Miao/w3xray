"""Lossless complete-text presentation for object details."""

from __future__ import annotations

from enum import StrEnum

from .map_data import GameObject, MapData
from .object_text_models import ObjectTextRecord, TextSelectionReason


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
    """Render every record readable-first with compact provenance.

    每条记录只出现一次：可读正文为主体，原始值仅在逐字不同时
    以“原始：”一行附加，出处元数据压缩为单行证据行，不丢证据。
    """
    records = records_for_text_view(
        md.object_texts.for_object(obj.category, obj.obj_id), view
    )
    if not records:
        return "\n【完整文本】\n（未发现该对象的逐字段文本证据）\n"
    blocks = ["\n【完整文本】"]
    for group in _merge_identical_records(records):
        blocks.append(_format_text_record(group))
    return "\n\n".join(blocks) + "\n"


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


def _format_text_record(records: tuple[ObjectTextRecord, ...]) -> str:
    first = records[0]
    level = "通用" if first.level is None else f"等级 {first.level}"
    role = " + ".join(record.role for record in records)
    lines = [f"── {role}｜{level}｜{first.state.value} ──"]
    readable = first.readable_value
    lines.append(readable if readable else "（空文本）")
    if first.raw_value != readable:
        lines.append(f"原始：{first.raw_value}")
    lines.append(_format_evidence_line(records))
    if first.conflict_group:
        lines.append(f"冲突组：{first.conflict_group}")
    if first.placeholder:
        lines.append("占位状态：是")
    return "\n".join(lines)


def _format_evidence_line(records: tuple[ObjectTextRecord, ...]) -> str:
    """Compress source, field keys, priority, ordinals, and selection into one line.

    “最高优先级唯一值”是默认当选原因，“当前值”在当前视图下必然成立，
    两者都不再单列；异常原因（冲突、低优先级等）与“非当前”仍然保留。
    """
    first = records[0]
    source = (
        " · ".join(value for value in (first.source_kind, first.source_path) if value)
        or "未记录"
    )
    parts = [source]
    keys = "、".join(record.field_key for record in records if record.field_key)
    if keys:
        parts.append(keys)
    parts.append(f"优先级 {first.source_priority}")
    parts.append(
        "序号 " + "、".join(str(record.evidence_ordinal) for record in records)
    )
    if not first.is_current:
        parts.append("非当前")
    if first.selection_reason is not TextSelectionReason.HIGHEST_PRIORITY_VALUE:
        parts.append(first.selection_reason.value)
    return "证据：" + " ｜ ".join(parts)
