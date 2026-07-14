"""Lossless TSV and completeness reports for complete object text."""

from __future__ import annotations

from collections import Counter
from typing import Final

from .batch_tsv import format_tsv_rows
from .object_text_models import ObjectTextIndex, ObjectTextState

_HEADER: Final = (
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
)


def format_object_text_tsv(index: ObjectTextIndex) -> str:
    """Render every complete-text evidence row without altering its values."""
    rows: list[tuple[str, ...]] = [_HEADER]
    rows.extend(
        (
            record.category,
            record.object_id,
            record.base_id,
            record.object_name,
            _yes_no(record.is_custom),
            record.role,
            record.field_key,
            record.field_label,
            "" if record.level is None else str(record.level),
            record.raw_value,
            record.readable_value,
            record.source_kind,
            record.source_path,
            record.state.value,
            _yes_no(record.placeholder),
            record.conflict_group,
            str(record.evidence_ordinal),
        )
        for record in index.records
    )
    return format_tsv_rows(rows)


def format_object_text_completeness(index: ObjectTextIndex) -> str:
    """List all seven source states, including explicit zero counts."""
    counts = Counter(record.state for record in index.records)
    return (
        "\n".join(f"{state.value}：{counts[state]}" for state in ObjectTextState) + "\n"
    )


def _yes_no(value: bool) -> str:
    return "是" if value else "否"
