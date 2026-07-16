"""Strict legacy TSV parsing and ordered candidate proof checks."""

from __future__ import annotations

import csv
import hashlib
from io import StringIO
import re
from collections.abc import Sequence
from typing import Final

from .base_objects import BASE_OBJECTS
from .batch_tsv import decode_tsv_cell, format_tsv_rows
from .description_cache_migration_models import (
    DescriptionCacheMigrationError,
    DescriptionCacheRejection,
    DescriptionCacheRejectionReason,
    LegacyDescriptionCacheRow,
    LegacyDescriptionReportRow,
    LegacySourceReport,
    ProvenDescriptionCandidate,
)
from .description_cache_schema import (
    LEGACY_CACHE_HEADER,
    LEGACY_DESCRIPTION_HEADER,
    is_placeholder,
)
from .object_text_evidence import readable_text


_RAWCODE: Final = re.compile(r"[!-~]{4}")
_LEVEL: Final = re.compile(r"0|[1-9][0-9]*")
_SUPPORTED_ROLES: Final = frozenset(("基础提示", "扩展提示"))


def parse_legacy_cache(
    payload: bytes,
    source: str,
) -> tuple[LegacyDescriptionCacheRow, ...]:
    """Parse an exact schema-2 candidate table without semantic guessing."""
    rows = _parse_tsv(payload, source, LEGACY_CACHE_HEADER)
    return tuple(
        LegacyDescriptionCacheRow(number, *row)
        for number, row in enumerate(rows, start=2)
    )


def parse_legacy_report(
    payload: bytes,
    source: str,
) -> tuple[LegacyDescriptionReportRow, ...]:
    """Parse one exact historical per-map description report."""
    rows = _parse_tsv(payload, source, LEGACY_DESCRIPTION_HEADER)
    return tuple(
        LegacyDescriptionReportRow(number, row)
        for number, row in enumerate(rows, start=2)
    )


def prove_candidate(
    candidate: LegacyDescriptionCacheRow,
    reports: Sequence[LegacySourceReport],
) -> ProvenDescriptionCandidate | DescriptionCacheRejection:
    """Apply the documented semantic proof checks in stable order."""
    base = BASE_OBJECTS.get(candidate.base_id)
    if base is None or base[0] != candidate.category:
        return _reject(candidate, DescriptionCacheRejectionReason.NOT_BASE_OBJECT)
    level_is_valid, level = _candidate_level(candidate)
    if (
        _RAWCODE.fullmatch(candidate.base_id) is None
        or not candidate.category
        or not level_is_valid
        or is_placeholder(candidate.raw_value)
    ):
        return _reject(candidate, DescriptionCacheRejectionReason.INVALID_IDENTITY)
    if candidate.role not in _SUPPORTED_ROLES:
        return _reject(candidate, DescriptionCacheRejectionReason.UNSUPPORTED_ROLE)
    matching_reports = tuple(
        report
        for report in reports
        if report.state.source_sha256 == candidate.source_map_sha256
    )
    if len(matching_reports) != 1:
        return _reject(candidate, DescriptionCacheRejectionReason.SOURCE_MAP_UNKNOWN)
    report = matching_reports[0]
    expected_path = f"{report.path}#base:{candidate.base_id}"
    if candidate.source_path != expected_path:
        return _reject(candidate, DescriptionCacheRejectionReason.SOURCE_PATH_ESCAPE)
    if report.sha256 is None:
        return _reject(candidate, DescriptionCacheRejectionReason.SOURCE_REPORT_MISSING)
    matches = tuple(
        row for row in report.rows if _matches_identity(row, candidate, level)
    )
    if len(matches) != 1:
        return _reject(candidate, DescriptionCacheRejectionReason.SOURCE_ROW_MISSING)
    report_row = matches[0]
    raw, readable, source_label = _role_values(report_row, candidate.role)
    if raw != candidate.raw_value:
        return _reject(candidate, DescriptionCacheRejectionReason.SOURCE_ROW_MISSING)
    if source_label != f"base:{candidate.base_id}":
        return _reject(candidate, DescriptionCacheRejectionReason.SOURCE_LABEL_MISMATCH)
    if (
        readable != candidate.readable_value
        or readable_text(candidate.raw_value) != candidate.readable_value
    ):
        return _reject(candidate, DescriptionCacheRejectionReason.READABLE_MISMATCH)
    if not _candidate_round_trips(candidate):
        return _reject(
            candidate, DescriptionCacheRejectionReason.TSV_ROUND_TRIP_MISMATCH
        )
    row_payload = format_tsv_rows((report_row.cells,)).encode("utf-8")
    return ProvenDescriptionCandidate(
        candidate,
        level,
        report.path,
        report.sha256,
        report_row.row_number,
        hashlib.sha256(row_payload).hexdigest(),
        source_label,
    )


def _parse_tsv(
    payload: bytes,
    source: str,
    header: tuple[str, ...],
) -> tuple[tuple[str, ...], ...]:
    try:
        text = payload.decode("utf-8")
        with StringIO(text, newline="") as handle:
            parsed = tuple(
                tuple(decode_tsv_cell(cell) for cell in row)
                for row in csv.reader(handle, delimiter="\t", strict=True)
            )
    except (UnicodeError, csv.Error) as exc:
        raise DescriptionCacheMigrationError(
            f"legacy TSV is unreadable: {source}: {type(exc).__name__}"
        ) from exc
    if not parsed or parsed[0] != header:
        raise DescriptionCacheMigrationError(f"legacy TSV header mismatch: {source}")
    if any(len(row) != len(header) for row in parsed[1:]):
        raise DescriptionCacheMigrationError(f"legacy TSV row width mismatch: {source}")
    return parsed[1:]


def _candidate_level(candidate: LegacyDescriptionCacheRow) -> tuple[bool, int | None]:
    if not candidate.level_text:
        return True, None
    if _LEVEL.fullmatch(candidate.level_text) is None:
        return False, None
    return True, int(candidate.level_text)


def _matches_identity(
    row: LegacyDescriptionReportRow,
    candidate: LegacyDescriptionCacheRow,
    level: int | None,
) -> bool:
    cells = row.cells
    level_text = "" if level is None else str(level)
    return (
        cells[0] == candidate.category
        and cells[1] == candidate.base_id
        and cells[2] == candidate.base_id
        and cells[4] == "否"
        and cells[5] == level_text
        and cells[12] == "客户端补全"
    )


def _role_values(
    row: LegacyDescriptionReportRow,
    role: str,
) -> tuple[str, str, str]:
    start = 6 if role == "基础提示" else 9
    return row.cells[start], row.cells[start + 1], row.cells[start + 2]


def _candidate_round_trips(candidate: LegacyDescriptionCacheRow) -> bool:
    try:
        payload = format_tsv_rows((candidate.cells,)).encode("utf-8")
        rows = _parse_tsv(payload, "candidate round-trip", candidate.cells)
    except UnicodeError, DescriptionCacheMigrationError:
        return False
    return not rows


def _reject(
    candidate: LegacyDescriptionCacheRow,
    reason: DescriptionCacheRejectionReason,
) -> DescriptionCacheRejection:
    return DescriptionCacheRejection(
        candidate.row_number,
        candidate.category,
        candidate.base_id,
        candidate.role,
        candidate.level_text,
        candidate.raw_value,
        candidate.readable_value,
        candidate.source_map_sha256,
        candidate.source_path,
        reason,
        reason.value,
    )


__all__ = ("parse_legacy_cache", "parse_legacy_report", "prove_candidate")
