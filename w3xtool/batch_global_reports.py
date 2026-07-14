"""Deterministic summaries for one complete batch state."""

from __future__ import annotations

from .batch_models import BatchState, MapBatchResult, MapBatchState
from .batch_tsv import format_tsv_rows


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
    return format_tsv_rows(rows)


def format_retry_tsv(state: BatchState) -> str:
    """List only results that a later run may need to retry."""
    rows = [("源路径", "状态", "阶段", "首个错误")]
    rows.extend(
        (result.source.path, result.state.value, result.stage, result.first_error)
        for result in sorted(state.results, key=_result_key)
        if result.state is not MapBatchState.COMPLETE
    )
    return format_tsv_rows(rows)


def _result_key(result: MapBatchResult) -> tuple[str, str]:
    return result.source.path.casefold(), result.source.path
