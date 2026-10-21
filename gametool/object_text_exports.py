"""Lossless TSV and completeness reports for complete object text."""

from __future__ import annotations

from collections import Counter
from typing import Final

from .batch_tsv import format_tsv_rows
from .base_names import BASE_CATEGORIES, BASE_NAMES_EN
from .object_text_models import ObjectTextIndex, ObjectTextRecord, ObjectTextState

OBJECT_TEXT_REPORT_HEADER: Final = (
    "分类",
    "对象ID",
    "基础ID",
    "名称",
    "自定义",
    "文本角色",
    "规范字段身份",
    "字段键",
    "字段标签",
    "等级/变体",
    "原始全文",
    "可读全文",
    "来源类型",
    "来源路径",
    "证据优先级",
    "状态",
    "占位",
    "冲突组",
    "是否当前值",
    "选择原因",
    "证据序号",
    "英文名",
    "细类",
)
# 2026-09 起在表尾追加了双语列。历史批次产物表头缺这两列，
# 回读校验按 legacy 变体兼容（见 batch_report_reader.read_report_rows_bytes）。
OBJECT_TEXT_REPORT_LEGACY_HEADERS: Final[tuple[tuple[str, ...], ...]] = (
    OBJECT_TEXT_REPORT_HEADER[:-2],
)


def _english_name(record: ObjectTextRecord) -> str:
    return (
        BASE_NAMES_EN.get(record.base_id) or BASE_NAMES_EN.get(record.object_id) or ""
    )


def _fine_category(record: ObjectTextRecord) -> str:
    fine = BASE_CATEGORIES.get(record.base_id) or BASE_CATEGORIES.get(record.object_id)
    return "" if fine is None else fine[0]


def format_object_text_tsv(index: ObjectTextIndex) -> str:
    """Render every complete-text evidence row without altering its values."""
    rows: list[tuple[str, ...]] = [OBJECT_TEXT_REPORT_HEADER]
    rows.extend(
        (
            record.category,
            record.object_id,
            record.base_id,
            record.object_name,
            _yes_no(record.is_custom),
            record.role,
            record.semantic_field,
            record.field_key,
            record.field_label,
            "" if record.level is None else str(record.level),
            record.raw_value,
            record.readable_value,
            record.source_kind,
            record.source_path,
            str(record.source_priority),
            record.state.value,
            _yes_no(record.placeholder),
            record.conflict_group,
            _yes_no(record.is_current),
            record.selection_reason.value,
            str(record.evidence_ordinal),
            _english_name(record),
            _fine_category(record),
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
