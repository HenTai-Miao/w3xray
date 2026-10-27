"""Knowledge-pack formatting for component extraction diagnostics."""

from __future__ import annotations

from .map_data import MapData
from .presentation_safety import tsv_cell as _tsv


def format_component_diagnostics_tsv(
    md: MapData, *, include_children: bool = False
) -> str:
    """Format ordered component diagnostics as stable TSV rows."""
    header = "组件\t来源\t阶段\t级别\t异常类型\t可恢复\t消息"
    rows = [header + ("\t地图\t地图来源" if include_children else "")]
    pending = [md]
    while pending:
        current = pending.pop()
        for item in current.diagnostics:
            cells = (
                _tsv(item.component),
                _tsv(item.source),
                _tsv(item.stage),
                item.severity.value,
                _tsv(item.exception_type),
                "是" if item.recoverable else "否",
                _tsv(item.message),
            )
            if include_children:
                cells += (
                    _tsv(current.name),
                    _tsv(current.path),
                )
            rows.append("\t".join(cells))
        if include_children:
            pending.extend(reversed(current.sub_maps))
    return "\n".join(rows) + "\n"
