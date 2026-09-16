"""GUI report block for UI/TRIGSTR text extraction."""

from __future__ import annotations

from .api import MapData
from .gui_reports import GuiReportBlock
from .ui_texts import build_ui_text_report

_MAX_SITES_SHOWN = 8


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
    lines.extend(_grouped_reference_lines(report))
    return GuiReportBlock("UI文本", tuple(lines), report.unresolved_count)


def _grouped_reference_lines(report) -> tuple[str, ...]:
    """Collapse repeated TRIGSTR references into one line with site counts.

    同一字符串常被脚本多处引用，逐条列出会重复同一文本几十次；
    按引用首次出现顺序分组，正文只出现一次。
    """
    sites_by_reference: dict[tuple[str, str], list[str]] = {}
    for ref in report.references:
        sites_by_reference.setdefault((ref.trigstr, ref.text or ""), []).append(
            f"{ref.source}:{ref.line}"
        )
    lines: list[str] = []
    for (trigstr, text), sites in sites_by_reference.items():
        if len(sites) == 1:
            lines.append(f"{trigstr} -> {text or '(未解析)'}")
            continue
        lines.append(f"{trigstr} -> {text or '(未解析)'}（×{len(sites)}）")
        shown = "、".join(sites[:_MAX_SITES_SHOWN])
        if len(sites) > _MAX_SITES_SHOWN:
            shown += f" 等{len(sites)}处"
        lines.append(f"  引用位置：{shown}")
    return tuple(lines)
