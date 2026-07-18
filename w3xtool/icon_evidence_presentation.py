"""Readable exact icon-evidence sections for GUI detail panes."""

from __future__ import annotations

from .icon_evidence_query import IconGapViewRow
from .map_data import GameObject, MapData


def format_icon_gap_evidence(row: IconGapViewRow) -> str:
    """Render one immutable row without implying candidate adoption."""
    lines = ["【图标候选（未采用）】" if row.candidate else "【图标缺口证据】"]
    lines.extend((f"地图：{row.map_path}", f"路径：{row.path}", f"原因：{row.reason}"))
    if row.category or row.rawcode:
        lines.append(f"对象：{row.category} {row.rawcode}".strip())
    if row.archive_status:
        lines.append(f"归档状态：{row.archive_status}")
    lines.append(f"引用数：{row.reference_count}")
    lines.append(row.detail)
    return "\n".join(lines) + "\n"


def format_object_icon_evidence_section(md: MapData, obj: GameObject) -> str:
    """Show only strict index evidence bound to this exact object identity."""
    rows = md.icon_evidence.for_object(obj.category, obj.obj_id)
    if not rows:
        return "\n【图标证据】\n（未发现严格图标字段证据）\n"
    blocks = ["\n【图标证据】"]
    for row in rows:
        reference = row.reference
        blocks.append(
            "\n".join(
                (
                    f"字段：{reference.field_label or reference.field_key or '未命名'}",
                    f"请求路径：{reference.requested_path}",
                    f"规范路径：{reference.normalized_path}",
                    f"证据类型：{type(row).__name__}",
                )
            )
        )
    return "\n\n".join(blocks) + "\n"
