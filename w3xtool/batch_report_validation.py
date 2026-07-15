"""Streaming schema and count checks for required per-map reports."""

from __future__ import annotations

from collections import Counter
import csv
from pathlib import Path
import sys

from .batch_manifest_models import ManifestResultSummary
from .batch_reports import DESCRIPTION_REPORT_HEADER, ICON_REPORT_HEADER
from .item_relation_exports import (
    ACQUISITION_REPORT_HEADER,
    EQUIPMENT_SKILL_REPORT_HEADER,
)
from .object_text_exports import OBJECT_TEXT_REPORT_HEADER


class BatchReportValidationError(ValueError):
    """A required publication report has an invalid tabular schema."""

    __slots__ = ("detail",)

    detail: str

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail

    def __str__(self) -> str:
        return self.detail


def validate_report_summaries(
    directory: Path,
    summary: ManifestResultSummary,
) -> str | None:
    """Return a stable mismatch detail or None when schemas/counts agree."""
    legacy_rows = _read_rows(directory / "对象描述.tsv", DESCRIPTION_REPORT_HEADER)
    object_ids = {(row[0], row[1]) for row in legacy_rows}
    if len(object_ids) != summary.object_count:
        return "object_count"

    icon_rows = _read_rows(directory / "图标索引.tsv", ICON_REPORT_HEADER)
    if sum(row[0] == "具名" for row in icon_rows) != summary.named_icon_count:
        return "named_icon_count"
    if sum(row[0] == "匿名" for row in icon_rows) != summary.anonymous_icon_count:
        return "anonymous_icon_count"
    if sum(_yes(row[8]) for row in icon_rows) != summary.original_written_count:
        return "original_written_count"
    if sum(_yes(row[9]) for row in icon_rows) != summary.png_written_count:
        return "png_written_count"

    text_rows = _read_rows(
        directory / "对象完整描述.tsv",
        OBJECT_TEXT_REPORT_HEADER,
    )
    text_counts = Counter(row[13] for row in text_rows)
    if not _counts_match(summary.description_counts, text_counts):
        return "description_counts"

    acquisition_rows = _read_rows(
        directory / "掉落与获取关系.tsv",
        ACQUISITION_REPORT_HEADER,
    )
    skill_rows = _read_rows(
        directory / "装备技能关系.tsv",
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


def _read_rows(path: Path, header: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    previous_limit = csv.field_size_limit()
    try:
        csv.field_size_limit(sys.maxsize)
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle, delimiter="\t")
            first = next(reader, None)
            if first is None or tuple(first) != header:
                raise BatchReportValidationError(
                    f"unexpected report header: {path.name}"
                )
            rows = tuple(tuple(row) for row in reader)
    finally:
        csv.field_size_limit(previous_limit)
    if any(len(row) != len(header) for row in rows):
        raise BatchReportValidationError(f"malformed report row: {path.name}")
    return rows


def _counts_match(
    expected: tuple[tuple[str, int], ...],
    actual: Counter[str],
) -> bool:
    expected_labels = {label for label, _count in expected}
    return all(actual[label] == count for label, count in expected) and not (
        set(actual) - expected_labels
    )


def _yes(value: str) -> bool:
    return value == "是"
