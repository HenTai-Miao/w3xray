"""Schema and count reconciliation for per-map icon reports."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from .batch_icon_reports import ICON_REPORT_HEADER
from .batch_manifest_models import ManifestResultSummary
from .batch_report_reader import BatchReportValidationError, read_report_rows
from .icon_evidence_counts import IconIntegrityCounts
from .icon_evidence_exports import UNRESOLVED_ICON_HEADER
from .icon_evidence_models import IconGapReason
from .icon_gap_reference_codec import parse_icon_gap_references
from .icon_path_evidence import plan_icon_path
from .icon_report_map_codec import parse_icon_report_map_identities

_INTEGRITY_LABELS: Final = (
    "有效引用",
    "已解析引用",
    "过滤字段",
    "具名未解析",
    "未解析引用",
    "匿名载荷",
    "匿名读取失败",
    "原始写出失败",
    "PNG失败",
)


def validate_icon_report_summaries(
    directory: Path,
    summary: ManifestResultSummary,
) -> str | None:
    """Return the first resolved/gap/write counter mismatch, if any."""
    icon_rows = read_report_rows(directory / "图标索引.tsv", ICON_REPORT_HEADER)
    if sum(row[0] == "具名" for row in icon_rows) != summary.named_icon_count:
        return "named_icon_count"
    if sum(row[0] == "匿名" for row in icon_rows) != summary.anonymous_icon_count:
        return "anonymous_icon_count"
    original_writes = tuple(_yes(row[9]) for row in icon_rows)
    png_writes = tuple(_yes(row[10]) for row in icon_rows)
    if sum(original_writes) != summary.original_written_count:
        return "original_written_count"
    if sum(png_writes) != summary.png_written_count:
        return "png_written_count"
    if sum(not written for written in original_writes) != (
        summary.original_write_failure_count
    ):
        return "original_write_failure_count"
    if (
        sum(
            original and not png
            for original, png in zip(original_writes, png_writes, strict=True)
        )
        != summary.png_failure_count
    ):
        return "png_failure_count"

    gap_rows = read_report_rows(directory / "图标未解析.tsv", UNRESOLVED_ICON_HEADER)
    unresolved_references = _validate_gap_rows(gap_rows, icon_rows)
    if len(gap_rows) != summary.unresolved_icon_count:
        return "unresolved_icon_count"
    if unresolved_references != summary.unresolved_icon_reference_count:
        return "unresolved_icon_reference_count"
    integrity = _read_icon_integrity(directory / "图标完整性.txt")
    checks = (
        (integrity.valid_reference_count, summary.valid_icon_reference_count),
        (integrity.resolved_reference_count, summary.resolved_icon_reference_count),
        (integrity.filtered_field_count, summary.filtered_icon_field_count),
        (integrity.normalized_gap_count, summary.unresolved_icon_count),
        (
            integrity.unresolved_reference_count,
            summary.unresolved_icon_reference_count,
        ),
        (integrity.anonymous_payload_count, summary.anonymous_icon_count),
        (
            integrity.anonymous_read_failure_count,
            summary.anonymous_read_failure_count,
        ),
        (
            integrity.original_write_failure_count,
            summary.original_write_failure_count,
        ),
        (integrity.png_failure_count, summary.png_failure_count),
    )
    labels = (
        "valid_icon_reference_count",
        "resolved_icon_reference_count",
        "filtered_icon_field_count",
        "unresolved_icon_count",
        "unresolved_icon_reference_count",
        "anonymous_icon_count",
        "anonymous_read_failure_count",
        "original_write_failure_count",
        "png_failure_count",
    )
    mismatch = next(
        (
            label
            for label, (actual, expected) in zip(labels, checks, strict=True)
            if actual != expected
        ),
        None,
    )
    if mismatch is not None:
        return mismatch
    if integrity.valid_reference_count != (
        integrity.resolved_reference_count + integrity.unresolved_reference_count
    ):
        return "valid_icon_reference_count"
    if integrity.failure_count != summary.icon_failure_count:
        return "icon_failure_count"
    return None


def _validate_gap_rows(
    rows: tuple[tuple[str, ...], ...],
    icon_rows: tuple[tuple[str, ...], ...],
) -> int:
    identities: set[tuple[str, str, str]] = set()
    resolved_identities: set[tuple[str, str, str]] = set()
    for row in icon_rows:
        if row[0] != "具名":
            continue
        normalized = plan_icon_path(row[1]).normalized
        if not normalized:
            continue
        resolved_identities.update(
            (item.map_path.casefold(), item.map_sha256, normalized.casefold())
            for item in parse_icon_report_map_identities(row[14])
        )
    reference_count = 0
    for row in rows:
        normalized = row[4]
        plan = plan_icon_path(normalized)
        if not normalized or plan.normalized != normalized:
            raise BatchReportValidationError("invalid normalized icon gap path")
        try:
            _ = IconGapReason(row[6])
        except ValueError as exc:
            raise BatchReportValidationError("invalid icon gap reason") from exc
        references = parse_icon_gap_references(row[12])
        if any(item.map.casefold() != row[0].casefold() for item in references):
            raise BatchReportValidationError("icon gap reference map mismatch")
        declared = _nonnegative_text(row[11], "icon gap reference count")
        if declared != len(references):
            raise BatchReportValidationError("icon gap reference count mismatch")
        identity = row[0].casefold(), row[1], normalized.casefold()
        if identity in identities:
            raise BatchReportValidationError("duplicate icon gap path identity")
        identities.add(identity)
        if identity in resolved_identities:
            raise BatchReportValidationError("resolved/gap path conflict")
        reference_count += declared
    return reference_count


def _read_icon_integrity(path: Path) -> IconIntegrityCounts:
    values: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split("：", 1)
        if len(parts) != 2 or parts[0] in values:
            raise BatchReportValidationError("malformed icon integrity line")
        label, raw_count = parts
        values[label] = _nonnegative_text(raw_count, "icon integrity count")
    if tuple(values) != _INTEGRITY_LABELS:
        raise BatchReportValidationError("unexpected icon integrity labels")
    return IconIntegrityCounts(
        values["有效引用"],
        values["已解析引用"],
        values["过滤字段"],
        values["具名未解析"],
        values["未解析引用"],
        values["匿名载荷"],
        values["匿名读取失败"],
        values["原始写出失败"],
        values["PNG失败"],
    )


def _yes(value: str) -> bool:
    if value not in ("是", "否"):
        raise BatchReportValidationError("invalid boolean report cell")
    return value == "是"


def _nonnegative_text(value: str, label: str) -> int:
    if not value.isdecimal():
        raise BatchReportValidationError(f"invalid {label}")
    return int(value)
