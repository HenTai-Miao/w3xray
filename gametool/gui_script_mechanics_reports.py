"""GUI report block for script-side engine mechanisms."""

from __future__ import annotations

from .api import MapData
from .gui_report_types import GuiReportBlock
from .script_mechanics import map_script_mechanisms


def build_script_mechanics_block(md: MapData) -> GuiReportBlock:
    features, implicit, marks = map_script_mechanisms(md)
    if not features and not implicit and not marks:
        return GuiReportBlock("脚本机制", ())
    lines = [
        f"特征 {len(features)}",
        f"隐式对象码 {len(implicit)}",
        f"运行时默认池 {len(marks)}",
    ]
    if features:
        lines.append("特征 " + "、".join(features))
    if implicit:
        lines.append("对象码 " + "、".join(sorted(implicit)))
    lines.extend(f"{mark.label}: {mark.detail}" for mark in marks)
    return GuiReportBlock("脚本机制", tuple(lines))
