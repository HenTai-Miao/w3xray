"""Streaming schema and count checks for required per-map reports."""

from __future__ import annotations

from collections import Counter
from typing import Final

from .batch_evidence_report_validation import validate_evidence_report_summaries
from .batch_icon_report_validation import validate_icon_report_summaries
from .batch_manifest_models import ManifestResultSummary, VerifiedReportSet
from .batch_report_reader import read_report_rows_bytes
from .batch_reports import DESCRIPTION_REPORT_HEADER
from .item_relation_exports import (
    ACQUISITION_REPORT_HEADER,
    EQUIPMENT_SKILL_REPORT_HEADER,
)
from .object_text_exports import OBJECT_TEXT_REPORT_HEADER


_TEXT_STATE_COLUMN: Final = OBJECT_TEXT_REPORT_HEADER.index("状态")


def validate_report_summaries(
    reports: VerifiedReportSet,
    summary: ManifestResultSummary,
) -> str | None:
    """Return a stable mismatch detail or None when schemas/counts agree."""
    evidence_mismatch = validate_evidence_report_summaries(reports, summary)
    if evidence_mismatch is not None:
        return evidence_mismatch
    legacy_rows = read_report_rows_bytes(
        reports.content("对象描述.tsv"), "对象描述.tsv", DESCRIPTION_REPORT_HEADER
    )
    object_ids = {(row[0], row[1]) for row in legacy_rows}
    if len(object_ids) != summary.object_count:
        return "object_count"

    icon_mismatch = validate_icon_report_summaries(reports, summary)
    if icon_mismatch is not None:
        return icon_mismatch

    text_rows = read_report_rows_bytes(
        reports.content("对象完整描述.tsv"),
        "对象完整描述.tsv",
        OBJECT_TEXT_REPORT_HEADER,
    )
    text_counts = Counter(row[_TEXT_STATE_COLUMN] for row in text_rows)
    if not _counts_match(summary.description_counts, text_counts):
        return "description_counts"

    acquisition_rows = read_report_rows_bytes(
        reports.content("掉落与获取关系.tsv"),
        "掉落与获取关系.tsv",
        ACQUISITION_REPORT_HEADER,
    )
    skill_rows = read_report_rows_bytes(
        reports.content("装备技能关系.tsv"),
        "装备技能关系.tsv",
        EQUIPMENT_SKILL_REPORT_HEADER,
    )
    relation_counts = Counter(row[2] for row in acquisition_rows)
    relation_counts.update(row[3] for row in skill_rows)
    if not _counts_match(summary.relation_counts, relation_counts):
        return "relation_counts"
    incomplete = sum(row[24] != "完整" for row in acquisition_rows) + sum(
        row[9] != "完整" for row in skill_rows
    )
    if incomplete != summary.relation_incomplete_count:
        return "relation_incomplete_count"
    return None


def _counts_match(
    expected: tuple[tuple[str, int], ...],
    actual: Counter[str],
) -> bool:
    expected_labels = {label for label, _count in expected}
    return all(actual[label] == count for label, count in expected) and not (
        set(actual) - expected_labels
    )
