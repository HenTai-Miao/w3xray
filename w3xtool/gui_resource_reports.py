"""GUI report block for resource/config inventory status."""

from __future__ import annotations

from .api import MapData
from .gui_reports import GuiReportBlock
from .resource_inventory import build_resource_inventory

_WARNING_STATUSES = {"导入缺失", "仅引用"}


def build_resource_inventory_block(md: MapData) -> GuiReportBlock:
    """Build the resource inventory card for the analysis report."""
    inventory = build_resource_inventory(md)
    if not inventory.items:
        return GuiReportBlock("资源资产", ())

    lines = [
        f"资产清单 {len(inventory.items)}",
        "类型 " + _format_counts(inventory.kind_counts),
        "状态 " + _format_counts(inventory.status_counts),
    ]
    warning_items = [item for item in inventory.items if item.status in _WARNING_STATUSES]
    lines.extend(f"[警告] {item.status}: {item.path}" for item in warning_items[:8])
    if len(warning_items) > 8:
        lines.append(f"另有 {len(warning_items) - 8} 条异常，导出资料包查看 TSV。")
    return GuiReportBlock("资源资产", tuple(lines), len(warning_items))


def _format_counts(rows: tuple[tuple[str, int], ...]) -> str:
    return "、".join(f"{name} {count}" for name, count in rows)
