"""Knowledge-pack formatting for component extraction diagnostics."""

from __future__ import annotations

from .map_data import MapData
from .presentation_safety import tsv_cell as _tsv


def format_component_diagnostics_tsv(md: MapData) -> str:
    """Format ordered component diagnostics as stable TSV rows."""
    rows = ["组件\t来源\t阶段\t级别\t异常类型\t可恢复\t消息"]
    for item in md.diagnostics:
        rows.append("\t".join((
            _tsv(item.component),
            _tsv(item.source),
            _tsv(item.stage),
            item.severity.value,
            _tsv(item.exception_type),
            "是" if item.recoverable else "否",
            _tsv(item.message),
        )))
    return "\n".join(rows) + "\n"
