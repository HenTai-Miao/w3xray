"""GUI report block for script-side engine mechanisms."""

from __future__ import annotations

from .api import MapData
from .gui_reports import GuiReportBlock
from .script_mechanics import scan_script_features, scan_script_need_marks
from .script_sources import analysis_script_texts


def build_script_mechanics_block(md: MapData) -> GuiReportBlock:
    script = "\n".join(text for _name, text in analysis_script_texts(md))
    if not script:
        return GuiReportBlock("脚本机制", ())
    features, implicit = scan_script_features(script)
    marks = scan_script_need_marks(script)
    if not features and not implicit and not marks:
        return GuiReportBlock("脚本机制", ())
    lines = [
        f"特征 {len(features)}",
        f"隐式对象码 {len(implicit)}",
        f"运行时默认池 {len(marks)}",
    ]
    if features:
        lines.append("特征 " + "、".join(features[:8]))
    if implicit:
        lines.append("对象码 " + "、".join(sorted(implicit)[:12]))
    lines.extend(f"{mark.label}: {mark.detail}" for mark in marks[:8])
    return GuiReportBlock("脚本机制", tuple(lines))
