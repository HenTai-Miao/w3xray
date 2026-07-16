"""Revalidate every historical report bound by an owned description cache."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Final, assert_never

from .batch_tsv import format_tsv_rows
from .bounded_file import read_bounded_regular_file
from .description_cache_migration_models import (
    DescriptionCacheMigrationError,
    DescriptionCacheRejection,
    LegacyDescriptionCacheRow,
    LegacySourceReport,
    LegacyStateResult,
    ProvenDescriptionCandidate,
)
from .description_cache_migration_rows import parse_legacy_report, prove_candidate
from .description_cache_models import DescriptionCache
from .trusted_description_cache_tables import (
    DescriptionCacheSourceRecord,
    TrustedTableError,
    parse_source_level,
    parse_source_manifest,
    validate_rejection_table,
)


_MAX_REPORT_BYTES: Final = 512 * 1024 * 1024


class TrustedSourceError(ValueError):
    """A source or rejection row failed exact revalidation."""

    __slots__ = ("detail",)

    detail: str

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail

    def __str__(self) -> str:
        return self.detail


def validate_source_manifest(
    payload: bytes,
    cache: DescriptionCache,
    source_root: Path,
) -> None:
    """Rehash all source reports and replay every candidate proof."""
    try:
        records = parse_source_manifest(payload)
    except TrustedTableError as exc:
        raise TrustedSourceError(str(exc)) from exc
    identities = {
        (
            row.category,
            row.base_id,
            row.role,
            row.level_text,
            row.source_map_sha256,
            row.report_path,
            row.report_row_number,
        )
        for row in records
    }
    if len(identities) != len(records):
        raise TrustedSourceError("duplicate source manifest identity")
    proven_entries: set[tuple[str, str, str, int | None, str, str]] = set()
    for record in records:
        entries = cache.lookup(
            record.category,
            record.base_id,
            record.role,
            parse_source_level(record.level_text),
        )
        if len(entries) != 1:
            raise TrustedSourceError("source manifest row is not bound to cache")
        entry = entries[0]
        report = _source_report(record, source_root)
        candidate = LegacyDescriptionCacheRow(
            record.row_number,
            record.category,
            record.base_id,
            record.role,
            record.level_text,
            entry.raw_value,
            entry.readable_value,
            record.source_map_sha256,
            f"{record.report_path}#base:{record.base_id}",
        )
        match prove_candidate(candidate, (report,)):
            case ProvenDescriptionCandidate() as proven:
                if (
                    proven.report_row_number != record.report_row_number
                    or proven.report_row_sha256 != record.report_row_sha256
                    or proven.source_label != record.source_label
                ):
                    raise TrustedSourceError("source report row proof mismatch")
            case DescriptionCacheRejection() as rejection:
                raise TrustedSourceError(
                    f"source candidate rejected: {rejection.reason}"
                )
            case unreachable:
                assert_never(unreachable)
        proven_entries.add(
            (
                entry.category,
                entry.base_id,
                entry.role,
                entry.level,
                record.source_map_sha256,
                candidate.source_path,
            )
        )
    for entry in cache.entries:
        identity = (
            entry.category,
            entry.base_id,
            entry.role,
            entry.level,
            entry.source_map_sha256,
            entry.source_path,
        )
        if identity not in proven_entries:
            raise TrustedSourceError("cache entry has no exact source proof")


def _source_report(
    record: DescriptionCacheSourceRecord,
    root: Path,
) -> LegacySourceReport:
    path = Path(record.report_path)
    absolute = path.expanduser().absolute()
    if not path.is_absolute():
        raise TrustedSourceError("source report path is not absolute")
    if not absolute.is_relative_to(root):
        raise TrustedSourceError("source report escapes source root")
    if absolute.is_symlink() or not absolute.is_file():
        raise TrustedSourceError("source report is not a regular file or is a symlink")
    try:
        resolved = absolute.resolve(strict=True)
    except OSError as exc:
        raise TrustedSourceError(f"source report is unreadable: {exc}") from exc
    if resolved != absolute or not resolved.is_relative_to(root):
        raise TrustedSourceError("source report escapes source root through a symlink")
    payload = _read_stable(absolute)
    if hashlib.sha256(payload).hexdigest() != record.report_sha256:
        raise TrustedSourceError("source report hash mismatch")
    try:
        rows = parse_legacy_report(payload, str(absolute))
    except DescriptionCacheMigrationError as exc:
        raise TrustedSourceError(str(exc)) from exc
    selected = tuple(row for row in rows if row.row_number == record.report_row_number)
    if len(selected) != 1:
        raise TrustedSourceError("source report row is missing")
    row_digest = hashlib.sha256(
        format_tsv_rows((selected[0].cells,)).encode()
    ).hexdigest()
    if row_digest != record.report_row_sha256:
        raise TrustedSourceError("source report row hash mismatch")
    state = LegacyStateResult("", record.source_map_sha256, "", "published")
    return LegacySourceReport(state, absolute, record.report_sha256, rows)


def _read_stable(path: Path) -> bytes:
    try:
        first, identity = read_bounded_regular_file(path, _MAX_REPORT_BYTES)
        second, _again = read_bounded_regular_file(
            path,
            _MAX_REPORT_BYTES,
            expected=identity,
        )
    except OSError as exc:
        raise TrustedSourceError(f"source report is unreadable: {exc}") from exc
    if first != second:
        raise TrustedSourceError("source report changed while reading")
    return first


__all__ = ("TrustedSourceError", "validate_rejection_table", "validate_source_manifest")
