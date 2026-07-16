"""Legacy resolved-icon TSV and completeness report rendering."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final

from .batch_icon_models import IconExportRecord, IconExportState
from .batch_tsv import format_tsv_rows
from .icon_report_map_codec import format_icon_report_map_identities

ICON_REPORT_HEADER: Final = (
    "类型",
    "原始路径",
    "解析路径",
    "真实来源",
    "解析层",
    "块编号",
    "SHA256",
    "原始输出",
    "PNG输出",
    "原始已写出",
    "PNG已写出",
    "状态",
    "错误",
    "引用对象",
    "引用地图身份",
)


def format_icon_index_tsv(records: Iterable[IconExportRecord]) -> str:
    """Render icon evidence, publication status, and object references."""
    rows: list[tuple[str, ...]] = [ICON_REPORT_HEADER]
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
                ""
                if record.resolution_layer is None
                else record.resolution_layer.value,
                "" if record.block_index is None else str(record.block_index),
                record.sha256,
                record.original_relative_path,
                record.png_relative_path,
                _yes_no(record.original_written),
                _yes_no(record.png_written),
                record.state.value,
                record.error,
                references,
                format_icon_report_map_identities(record.objects),
            )
        )
    return format_tsv_rows(rows)


def format_icon_completeness(
    records: Iterable[IconExportRecord],
    *,
    unresolved_named_count: int = 0,
    restricted_block_count: int = 0,
) -> str:
    """Render the compatibility icon completeness summary."""
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


def _yes_no(value: bool) -> str:
    return "是" if value else "否"


def _icon_key(record: IconExportRecord) -> tuple[int, str, int]:
    return (
        int(record.kind.value != "具名"),
        record.requested_path.casefold(),
        record.block_index or -1,
    )
