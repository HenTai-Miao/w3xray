"""GUI report block for UI/TRIGSTR text extraction."""

from __future__ import annotations

from .api import MapData
from .gui_reports import GuiReportBlock
from .ui_texts import build_ui_text_report


def build_ui_text_block(md: MapData) -> GuiReportBlock:
    """Build the UI text card for the analysis report."""
    report = build_ui_text_report(md)
    if report.string_count == 0 and report.reference_count == 0:
        return GuiReportBlock("UI文本", ())
    lines = [
        f"字符串 {report.string_count}",
        f"引用 {report.reference_count}",
    ]
    if report.unresolved_count:
        lines.append(f"[警告] 未解析 {report.unresolved_count}")
    for ref in report.references:
        text = ref.text or "(未解析)"
        lines.append(f"{ref.source}:{ref.line} {ref.trigstr} -> {text}")
    return GuiReportBlock("UI文本", tuple(lines), report.unresolved_count)
