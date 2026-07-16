"""Lossless complete-text presentation for object details."""

from __future__ import annotations

from .map_data import GameObject, MapData
from .object_text_models import ObjectTextRecord


def format_complete_text_section(md: MapData, obj: GameObject) -> str:
    """Render every readable and raw text record without truncation."""
    records = md.object_texts.for_object(obj.category, obj.obj_id)
    if not records:
        return "\n【完整文本】\n（未发现该对象的逐字段文本证据）\n"
    readable = _format_text_view("可读版", records, raw=False)
    raw = _format_text_view("原始版", records, raw=True)
    return f"\n{readable}\n{raw}\n"


def _format_text_view(
    label: str,
    records: tuple[ObjectTextRecord, ...],
    *,
    raw: bool,
) -> str:
    blocks = [f"【完整文本：{label}】"]
    for record in records:
        blocks.append(_format_text_record(record, raw=raw))
    return "\n\n".join(blocks)


def _format_text_record(record: ObjectTextRecord, *, raw: bool) -> str:
    level = "通用" if record.level is None else f"等级 {record.level}"
    source = (
        " · ".join(value for value in (record.source_kind, record.source_path) if value)
        or "未记录"
    )
    lines = [
        f"── {record.role}｜{level}｜{record.state.value} ──",
        f"规范字段：{record.semantic_field}",
        f"字段：{record.field_label or '未命名'}（{record.field_key or '无字段键'}）",
        f"来源：{source}",
        f"证据优先级：{record.source_priority}｜当前值：{'是' if record.is_current else '否'}",
        f"选择原因：{record.selection_reason.value}",
        f"证据序号：{record.evidence_ordinal}",
    ]
    if record.conflict_group:
        lines.append(f"冲突组：{record.conflict_group}")
    if record.placeholder:
        lines.append("占位状态：是")
    value = record.raw_value if raw else record.readable_value
    lines.extend(("正文：", value if value else "（空文本）"))
    return "\n".join(lines)
