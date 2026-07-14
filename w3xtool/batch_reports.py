"""Deterministic TSV and text reports for batch extraction."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import Final

from .batch_descriptions import DescriptionRecord, DescriptionState
from .batch_icon_export import IconExportRecord, IconExportState
from .batch_models import BatchState, MapBatchResult, MapBatchState
from .batch_state_io import format_batch_state_json, parse_batch_state_json

__all__ = (
    "derive_map_state",
    "description_state_counts",
    "format_batch_state_json",
    "format_batch_summary_tsv",
    "format_description_completeness",
    "format_description_tsv",
    "format_icon_completeness",
    "format_icon_index_tsv",
    "format_map_summary",
    "format_retry_tsv",
    "parse_batch_state_json",
)

_DESCRIPTION_HEADER: Final = (
    "分类",
    "对象ID",
    "基础ID",
    "名称",
    "自定义",
    "等级",
    "原始提示",
    "可读提示",
    "提示来源",
    "原始说明",
    "可读说明",
    "说明来源",
    "完整性状态",
)
_ICON_HEADER: Final = (
    "类型",
    "原始路径",
    "解析路径",
    "真实来源",
    "块编号",
    "SHA256",
    "原始输出",
    "PNG输出",
    "原始已写出",
    "PNG已写出",
    "状态",
    "错误",
    "引用对象",
)


def format_description_tsv(records: Iterable[DescriptionRecord]) -> str:
    """Render raw and readable object descriptions without losing markup."""
    rows: list[tuple[str, ...]] = [_DESCRIPTION_HEADER]
    for record in sorted(records, key=_description_key):
        rows.append(
            (
                record.category,
                record.object_id,
                record.base_id,
                record.object_name,
                _yes_no(record.is_custom),
                "" if record.level is None else str(record.level),
                record.raw_tip,
                record.readable_tip,
                record.tip_source,
                record.raw_description,
                record.readable_description,
                record.description_source,
                record.state.value,
            )
        )
    return _format_rows(rows)


def format_icon_index_tsv(records: Iterable[IconExportRecord]) -> str:
    """Render icon evidence, publication status, and object references."""
    rows: list[tuple[str, ...]] = [_ICON_HEADER]
    for record in sorted(records, key=_icon_key):
        references = ";".join(
            f"{item.category}:{item.object_id}:{item.object_name}"
            for item in record.objects
        )
        rows.append(
            (
                record.kind.value,
                record.requested_path,
                record.resolved_path,
                record.source_path,
                "" if record.block_index is None else str(record.block_index),
                record.sha256,
                record.original_relative_path,
                record.png_relative_path,
                _yes_no(record.original_written),
                _yes_no(record.png_written),
                record.state.value,
                record.error,
                references,
            )
        )
    return _format_rows(rows)


def description_state_counts(
    records: Iterable[DescriptionRecord],
) -> tuple[tuple[str, int], ...]:
    """Count all four description states in declaration order."""
    counts = Counter(record.state for record in records)
    return tuple((state.value, counts[state]) for state in DescriptionState)


def derive_map_state(
    *,
    structural_error: bool,
    restricted_block_count: int,
    ledger_incomplete: bool,
    icons: Iterable[IconExportRecord],
    descriptions: Iterable[DescriptionRecord],
) -> MapBatchState:
    """Apply documented map-level completeness precedence."""
    if structural_error:
        return MapBatchState.FAILED
    if restricted_block_count:
        return MapBatchState.RESTRICTED
    icon_incomplete = any(
        record.state is not IconExportState.COMPLETE for record in icons
    )
    description_missing = any(
        record.state is DescriptionState.SOURCE_MISSING for record in descriptions
    )
    if ledger_incomplete or icon_incomplete or description_missing:
        return MapBatchState.PARTIAL
    return MapBatchState.COMPLETE


def format_map_summary(result: MapBatchResult) -> str:
    """Render a compact human-readable per-map outcome."""
    lines = (
        f"地图：{result.display_name}",
        f"源文件：{result.source.path}",
        f"源 SHA-256：{result.source.sha256}",
        f"状态：{result.state.value}",
        f"对象数：{result.object_count}",
        f"具名图标：{result.named_icon_count}",
        f"匿名图标：{result.anonymous_icon_count}",
        f"原始写出：{result.original_written_count}",
        f"PNG 成功：{result.png_written_count}",
        f"首个错误：{result.first_error}",
    )
    return "\n".join(lines) + "\n"


def format_icon_completeness(
    records: Iterable[IconExportRecord],
    *,
    unresolved_named_count: int = 0,
    restricted_block_count: int = 0,
) -> str:
    """Summarize icon writes and unresolved static boundaries."""
    items = tuple(records)
    return "\n".join(
        (
            f"已识别：{len(items)}",
            f"原始写出：{sum(item.original_written for item in items)}",
            f"PNG 成功：{sum(item.png_written for item in items)}",
            f"失败：{sum(item.state is not IconExportState.COMPLETE for item in items)}",
            f"具名未解析：{unresolved_named_count}",
            f"受限块：{restricted_block_count}",
            "",
        )
    )


def format_description_completeness(records: Iterable[DescriptionRecord]) -> str:
    """Summarize all four source/completeness states."""
    return "\n".join(
        (
            *(
                f"{label}：{count}"
                for label, count in description_state_counts(records)
            ),
            "",
        )
    )


def format_batch_summary_tsv(state: BatchState) -> str:
    """Render stable global result rows sorted by source path."""
    header = (
        "源路径",
        "地图名",
        "SHA256",
        "输出目录",
        "阶段",
        "状态",
        "对象数",
        "描述状态计数",
        "具名图标",
        "匿名图标",
        "原始写出",
        "PNG成功",
        "图标失败",
        "受限块",
        "耗时毫秒",
        "首个错误",
    )
    rows: list[tuple[str, ...]] = [header]
    for result in sorted(state.results, key=_result_key):
        counts = ";".join(
            f"{label}={count}" for label, count in result.description_counts
        )
        rows.append(
            (
                result.source.path,
                result.display_name,
                result.source.sha256,
                result.output_directory,
                result.stage,
                result.state.value,
                str(result.object_count),
                counts,
                str(result.named_icon_count),
                str(result.anonymous_icon_count),
                str(result.original_written_count),
                str(result.png_written_count),
                str(result.icon_failure_count),
                str(result.restricted_block_count),
                str(result.elapsed_ms),
                result.first_error,
            )
        )
    return _format_rows(rows)


def format_retry_tsv(state: BatchState) -> str:
    """List only results that a later run may need to retry."""
    rows = [("源路径", "状态", "阶段", "首个错误")]
    rows.extend(
        (result.source.path, result.state.value, result.stage, result.first_error)
        for result in sorted(state.results, key=_result_key)
        if result.state is not MapBatchState.COMPLETE
    )
    return _format_rows(rows)


def _format_rows(rows: Iterable[tuple[str, ...]]) -> str:
    return "".join("\t".join(_cell(value) for value in row) + "\n" for row in rows)


def _cell(value: str) -> str:
    return (
        value.replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\t", " ")
        .replace("\n", "\\n")
    )


def _yes_no(value: bool) -> str:
    return "是" if value else "否"


def _description_key(record: DescriptionRecord) -> tuple[str, str, int]:
    return (
        record.category.casefold(),
        record.object_id,
        -1 if record.level is None else record.level,
    )


def _icon_key(record: IconExportRecord) -> tuple[int, str, int]:
    return (
        int(record.kind.value != "具名"),
        record.requested_path.casefold(),
        record.block_index or -1,
    )


def _result_key(result: MapBatchResult) -> tuple[str, str]:
    return result.source.path.casefold(), result.source.path
