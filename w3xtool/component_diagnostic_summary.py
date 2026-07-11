"""Compact component diagnostics shared by CLI and GUI summaries."""

from __future__ import annotations

from collections.abc import Iterator

from .extraction_diagnostics import ExtractionDiagnostic
from .map_data import MapData


def iter_component_diagnostic_lines(md: MapData) -> Iterator[str]:
    """Yield a bounded CLI summary for retained component failures."""
    if not md.diagnostics:
        return
    yield f"  组件诊断: {len(md.diagnostics)}"
    for item in md.diagnostics[:8]:
        yield f"    - {format_component_diagnostic(item)}"
    if len(md.diagnostics) > 8:
        yield f"    …… 另有 {len(md.diagnostics) - 8} 条，导出资料包查看 TSV。"


def format_component_diagnostic(item: ExtractionDiagnostic) -> str:
    """Format one diagnostic without losing its source or exception type."""
    exception_type = item.exception_type or "无异常类型"
    return f"{item.component} · {item.source} · {exception_type} · {item.message}"
