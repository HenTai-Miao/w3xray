"""Readable exact icon-evidence sections for GUI detail panes."""

from __future__ import annotations

from typing import Final

from .icon_evidence_models import (
    FilteredIconEvidence,
    IconCandidateEvidence,
    IconGapReason,
    ResolvedIconEvidence,
    UnresolvedIconEvidence,
)
from .icon_evidence_query import IconGapViewRow
from .map_data import GameObject, MapData

_GAP_LABELS: Final[dict[IconGapReason, str]] = {
    IconGapReason.INVALID_REFERENCE: "引用无效",
    IconGapReason.NAMED_RESOURCE_MISSING: "具名资源缺失",
    IconGapReason.ANONYMOUS_PAYLOAD_UNBOUND: "匿名数据未绑定",
    IconGapReason.CLIENT_SOURCE_UNAVAILABLE: "客户端数据未提供",
    IconGapReason.HISTORICAL_CLIENT_MISS: "历史客户端未命中",
    IconGapReason.ARCHIVE_NAME_UNAVAILABLE: "归档名不可用",
    IconGapReason.ARCHIVE_BLOCK_DAMAGED: "归档块受损",
}


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
    """One compact line per strict evidence row bound to this exact identity."""
    rows = md.icon_evidence.for_object(obj.category, obj.obj_id)
    if not rows:
        return "\n【图标证据】\n（未发现严格图标字段证据）\n"
    lines = ["\n【图标证据】"]
    for row in rows:
        lines.append(_format_icon_row(row))
    return "\n".join(lines) + "\n"


def _format_icon_row(row: object) -> str:
    reference = getattr(row, "reference")
    path = reference.normalized_path or reference.requested_path or "（未记录路径）"
    label, resolved_path = _row_label(row)
    extras: list[str] = []
    if (
        reference.requested_path
        and reference.normalized_path
        and reference.requested_path != reference.normalized_path
    ):
        extras.append(f"请求 {reference.requested_path}")
    if resolved_path and resolved_path != path:
        extras.append(f"解析至 {resolved_path}")
    field = reference.field_label or reference.field_key
    if field:
        extras.append(f"字段 {field}")
    head = f"· {path} —— {label}"
    return head + (" ｜ " + " ｜ ".join(extras) if extras else "")


def _row_label(row: object) -> tuple[str, str]:
    """Human-readable state label plus the resolved path when bytes were found."""
    match row:
        case ResolvedIconEvidence():
            return "已解析", row.resolved_path
        case UnresolvedIconEvidence():
            reason = _GAP_LABELS.get(row.reason, row.reason.value)
            return f"未解析（{reason}）", ""
        case FilteredIconEvidence():
            return "已过滤（非图标字段）", ""
        case IconCandidateEvidence():
            return "候选（未采用）", row.candidate_path
    return type(row).__name__, ""
