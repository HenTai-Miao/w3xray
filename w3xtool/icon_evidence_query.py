"""Immutable GUI projections over strict icon-evidence indexes."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .batch_global_evidence_models import GlobalEvidenceIndex
from .icon_evidence_index import IconEvidenceIndex
from .icon_evidence_models import IconDiagnosticFlag
from .search import compile_query


@dataclass(frozen=True, slots=True)
class IconGapViewRow:
    row_id: str
    map_path: str
    map_sha256: str
    reason: str
    category: str
    rawcode: str
    path: str
    archive_status: str
    reference_count: int
    candidate: bool
    adopted: bool
    object_identity: tuple[str, str] | None
    detail: str


@dataclass(frozen=True, slots=True)
class IconGapFilter:
    query: str
    reason: str
    category: str
    archive_status: str
    show_candidates: bool


def map_icon_gap_rows(index: IconEvidenceIndex) -> tuple[IconGapViewRow, ...]:
    """Expand every unresolved reference without coalescing its reason."""
    rows: list[IconGapViewRow] = []
    for gap in index.unresolved:
        ref = gap.reference
        rows.append(
            IconGapViewRow(
                f"gap:{ref.map_sha256}:{ref.category}:{ref.object_id}:{ref.field_key}:{ref.normalized_path}",
                ref.map_path,
                ref.map_sha256,
                gap.reason.value,
                ref.category,
                ref.object_id,
                ref.normalized_path or ref.requested_path,
                _archive_status(gap.diagnostics),
                1,
                False,
                False,
                (ref.category, ref.object_id),
                _gap_detail(gap.diagnostics),
            )
        )
    return tuple(rows)


def global_icon_gap_rows(index: GlobalEvidenceIndex) -> tuple[IconGapViewRow, ...]:
    """Project global gaps and non-authoritative candidates as separate rows."""
    rows: list[IconGapViewRow] = []
    for gap in index.gaps:
        identity = None
        if len(gap.references) == 1:
            ref = gap.references[0]
            identity = (ref.category, ref.object_id)
        rows.append(
            IconGapViewRow(
                f"gap:{gap.map_sha256}:{gap.normalized_path}:{gap.reason.value}",
                gap.map_path,
                gap.map_sha256,
                gap.reason.value,
                "、".join(gap.object_categories),
                "、".join(gap.rawcodes),
                gap.normalized_path,
                _archive_status(gap.diagnostics),
                gap.reference_count,
                False,
                False,
                identity,
                _gap_detail(gap.diagnostics),
            )
        )
    for candidate in index.candidates:
        rows.append(
            IconGapViewRow(
                f"candidate:{candidate.kind.value}:{candidate.requested_map_sha256}:{candidate.requested_path}",
                "",
                candidate.requested_map_sha256,
                candidate.kind.value,
                "",
                "",
                candidate.requested_path,
                "",
                0,
                True,
                False,
                None,
                f"候选未采用：{candidate.candidate_path}",
            )
        )
    return tuple(rows)


def filter_icon_gap_rows(
    rows: Iterable[IconGapViewRow],
    criteria: IconGapFilter,
) -> tuple[IconGapViewRow, ...]:
    """Filter projections only; this never changes evidence or adoption."""
    compiled = compile_query(criteria.query.strip())
    visible: list[IconGapViewRow] = []
    for row in rows:
        if row.candidate is not criteria.show_candidates:
            continue
        if criteria.reason != "全部" and row.reason != criteria.reason:
            continue
        if criteria.category != "全部" and row.category != criteria.category:
            continue
        if (
            criteria.archive_status != "全部"
            and row.archive_status != criteria.archive_status
        ):
            continue
        blob = " ".join(
            (row.map_path, row.reason, row.category, row.rawcode, row.path, row.detail)
        )
        if criteria.query and compiled.score(blob) is None:
            continue
        visible.append(row)
    return tuple(visible)


def _archive_status(flags: tuple[IconDiagnosticFlag, ...]) -> str:
    if IconDiagnosticFlag.ARCHIVE_HAS_DAMAGED_BLOCK in flags:
        return "存在损坏块"
    if IconDiagnosticFlag.ARCHIVE_HAS_RESTRICTED_BLOCK in flags:
        return "存在受限块"
    if IconDiagnosticFlag.ARCHIVE_HAS_RAW_BLOCK in flags:
        return "存在原始块"
    return "完整"


def _gap_detail(flags: tuple[IconDiagnosticFlag, ...]) -> str:
    return "；".join(flag.value for flag in flags) or "完整字段证据"
