"""Required-report reconciliation for persisted schema-five evidence counters."""

from __future__ import annotations

from typing import assert_never

from .batch_manifest_models import ManifestResultSummary, VerifiedReportSet
from .batch_report_reader import BatchReportValidationError, read_report_rows_bytes
from .item_relation_exports import (
    ACQUISITION_REPORT_HEADER,
    EQUIPMENT_SKILL_REPORT_HEADER,
)
from .item_relation_models import RelationCompleteness
from .object_text_exports import OBJECT_TEXT_REPORT_HEADER
from .object_text_models import ObjectTextState


_TEXT_STATE = OBJECT_TEXT_REPORT_HEADER.index("状态")
_TEXT_CURRENT = OBJECT_TEXT_REPORT_HEADER.index("是否当前值")
_ACQUISITION_COMPLETENESS = ACQUISITION_REPORT_HEADER.index("完整性")
_SKILL_COMPLETENESS = EQUIPMENT_SKILL_REPORT_HEADER.index("完整性")


def validate_evidence_report_summaries(
    reports: VerifiedReportSet,
    summary: ManifestResultSummary,
) -> str | None:
    """Return the first mismatch for current-text and relation evidence counters."""
    text_mismatch = _validate_current_text(reports, summary)
    if text_mismatch is not None:
        return text_mismatch
    return _validate_relation_completeness(reports, summary)


def _validate_current_text(
    reports: VerifiedReportSet,
    summary: ManifestResultSummary,
) -> str | None:
    unavailable = 0
    conflict = 0
    rows = read_report_rows_bytes(
        reports.content("对象完整描述.tsv"),
        "对象完整描述.tsv",
        OBJECT_TEXT_REPORT_HEADER,
    )
    for row in rows:
        if not _yes_no(row[_TEXT_CURRENT]):
            continue
        state = _text_state(row[_TEXT_STATE])
        unavailable += int(state is ObjectTextState.SOURCE_UNAVAILABLE)
        conflict += int(state is ObjectTextState.SOURCE_CONFLICT)
    if unavailable != summary.current_source_unavailable_count:
        return "current_source_unavailable_count"
    if conflict != summary.current_source_conflict_count:
        return "current_source_conflict_count"
    return None


def _validate_relation_completeness(
    reports: VerifiedReportSet,
    summary: ManifestResultSummary,
) -> str | None:
    partial = 0
    unresolved = 0
    rows = (
        (ACQUISITION_REPORT_HEADER, _ACQUISITION_COMPLETENESS),
        (EQUIPMENT_SKILL_REPORT_HEADER, _SKILL_COMPLETENESS),
    )
    paths = ("掉落与获取关系.tsv", "装备技能关系.tsv")
    for path, (header, column) in zip(paths, rows, strict=True):
        for row in read_report_rows_bytes(reports.content(path), path, header):
            match _relation_completeness(row[column]):
                case RelationCompleteness.PARTIAL | RelationCompleteness.CONFLICT:
                    partial += 1
                case RelationCompleteness.UNRESOLVED:
                    unresolved += 1
                case RelationCompleteness.COMPLETE:
                    pass
                case unreachable:
                    assert_never(unreachable)
    if partial != summary.relation_partial_count:
        return "relation_partial_count"
    if unresolved != summary.unresolved_endpoint_count:
        return "unresolved_endpoint_count"
    return None


def _yes_no(value: str) -> bool:
    if value == "是":
        return True
    if value == "否":
        return False
    raise BatchReportValidationError("invalid current text marker")


def _text_state(value: str) -> ObjectTextState:
    try:
        return ObjectTextState(value)
    except ValueError as exc:
        raise BatchReportValidationError("invalid complete text state") from exc


def _relation_completeness(value: str) -> RelationCompleteness:
    try:
        return RelationCompleteness(value)
    except ValueError as exc:
        raise BatchReportValidationError("invalid relation completeness") from exc


__all__ = ("validate_evidence_report_summaries",)
