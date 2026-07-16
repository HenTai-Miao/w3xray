"""Revalidate every historical report bound by an owned description cache."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
from typing import Final, assert_never, override

from .anchored_source import AnchoredSourceError, AnchoredSourceRoot
from .batch_tsv import format_tsv_rows
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

    __slots__: tuple[str, ...] = ("detail",)

    detail: str

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail

    @override
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
    try:
        with AnchoredSourceRoot.open(source_root) as anchored_root:
            for record in records:
                entries = cache.lookup(
                    record.category,
                    record.base_id,
                    record.role,
                    parse_source_level(record.level_text),
                )
                if len(entries) != 1:
                    raise TrustedSourceError(
                        "source manifest row is not bound to cache"
                    )
                entry = entries[0]
                report = _source_report(record, source_root, anchored_root)
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
                    case ProvenDescriptionCandidate() as proof:
                        if (
                            proof.report_row_number != record.report_row_number
                            or proof.report_row_sha256 != record.report_row_sha256
                            or proof.source_label != record.source_label
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
    except AnchoredSourceError as exc:
        raise TrustedSourceError(f"source report is unreadable: {exc}") from exc
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
    anchored_root: AnchoredSourceRoot,
) -> LegacySourceReport:
    path = Path(record.report_path)
    absolute = path.expanduser().absolute()
    if not path.is_absolute():
        raise TrustedSourceError("source report path is not absolute")
    try:
        relative = absolute.relative_to(root)
    except ValueError as exc:
        raise TrustedSourceError("source report escapes source root") from exc
    if not relative.parts:
        raise TrustedSourceError("source report escapes source root")
    try:
        anchored = anchored_root.read(
            PurePosixPath(*relative.parts),
            _MAX_REPORT_BYTES,
        )
    except AnchoredSourceError as exc:
        raise TrustedSourceError(f"source report is unreadable: {exc}") from exc
    payload = anchored.payload
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


__all__ = ("TrustedSourceError", "validate_rejection_table", "validate_source_manifest")
