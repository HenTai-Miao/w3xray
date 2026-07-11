"""GUI block for extraction completeness diagnostics."""

from __future__ import annotations

from .api import MapData
from .component_diagnostic_summary import format_component_diagnostic
from .extraction_diagnostics import DiagnosticSeverity
from .extraction_completeness import build_extraction_completeness_report
from .gui_reports import GuiReportBlock


def build_extraction_completeness_block(md: MapData) -> GuiReportBlock:
    report = build_extraction_completeness_report(md)
    lines = [
        f"命名文件 {report.named_file_count}",
        f"源状态 {'可读取' if report.source_readable else '源文件不可读'}",
    ]
    if report.block_count is not None:
        percent = report.named_coverage_percent
        coverage = (
            f"{report.named_block_count}/{report.block_count}"
            if percent is None
            else f"{report.named_block_count}/{report.block_count} ({percent:.1f}%)"
        )
        lines.extend((
            f"命名覆盖 {coverage}",
            f"无名块 {report.anonymous_block_count or 0}",
            f"Unknown {report.recoverable_anonymous_count or 0}",
            f"UnknownRaw {report.raw_fallback_count or 0}",
        ))
    lines.extend(f"[警告] {warning}" for warning in report.warnings[:3])
    if md.diagnostics:
        lines.append(f"组件诊断 {len(md.diagnostics)}")
        lines.extend(
            f"[警告] {format_component_diagnostic(item)}"
            for item in md.diagnostics[:5]
        )
    component_warnings = sum(
        item.severity in {DiagnosticSeverity.WARNING, DiagnosticSeverity.ERROR}
        for item in md.diagnostics
    )
    return GuiReportBlock(
        "提取完整性",
        tuple(lines),
        len(report.warnings) + component_warnings,
    )
