"""Immutable per-block extraction evidence and aggregate status."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, override


_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}")


class ExtractionStatus(StrEnum):
    """One auditable outcome for a map extraction attempt."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    ENCRYPTED_BLOCKED = "encrypted_blocked"
    DAMAGED = "damaged"


class BlockState(StrEnum):
    """Outcome for one live archive block or supplemental file."""

    DECODED = "decoded"
    SUPPLEMENTED = "supplemented"
    RAW_ONLY = "raw_only"
    ENCRYPTED_BLOCKED = "encrypted_blocked"
    DAMAGED = "damaged"


class BlockSource(StrEnum):
    """Static evidence source that produced an entry."""

    ARCHIVE_NAMED = "archive_named"
    ARCHIVE_RECOVERED = "archive_recovered"
    COMPAT_KEY = "compat_key"
    COMPAT_PLAINTEXT = "compat_plaintext"
    AUTHOR_PLAINTEXT = "author_plaintext"
    RAW_PAYLOAD = "raw_payload"


@dataclass(frozen=True, slots=True)
class ExtractionLedgerError(ValueError):
    """Reject an internally inconsistent evidence record."""

    detail: str

    @override
    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True, slots=True)
class ExtractionEntry:
    """Verified extraction evidence for one block or supplemental path."""

    block_index: int | None
    internal_path: str
    state: BlockState
    source: BlockSource
    declared_size: int
    written_size: int
    sha256: str
    encrypted: bool
    error_code: str
    detail: str

    def __post_init__(self) -> None:
        if self.block_index is not None and self.block_index < 0:
            raise ExtractionLedgerError("block index must be non-negative")
        if not self.internal_path:
            raise ExtractionLedgerError("internal path must not be empty")
        if self.declared_size < 0 or self.written_size < 0:
            raise ExtractionLedgerError("entry sizes must be non-negative")
        if self.sha256 and _SHA256_RE.fullmatch(self.sha256) is None:
            raise ExtractionLedgerError("entry SHA-256 must be lowercase hexadecimal")
        if self.state in _VERIFIED_STATES and not self.sha256:
            raise ExtractionLedgerError("verified entry requires a SHA-256 digest")
        if self.written_size and not self.sha256:
            raise ExtractionLedgerError("written entry requires a SHA-256 digest")
        if self.state is BlockState.DAMAGED and self.written_size != 0:
            raise ExtractionLedgerError("unwritten entry must have written size zero")


@dataclass(frozen=True, slots=True)
class ExtractionLedger:
    """Versioned source identity, aggregate status, and ordered evidence."""

    source_path: str
    source_sha256: str
    status: ExtractionStatus
    entries: tuple[ExtractionEntry, ...]
    warnings: tuple[str, ...] = ()
    schema_version: int = 1

    def __post_init__(self) -> None:
        if _SHA256_RE.fullmatch(self.source_sha256) is None:
            raise ExtractionLedgerError("source SHA-256 must be lowercase hexadecimal")
        if self.schema_version != 1:
            raise ExtractionLedgerError("unsupported extraction ledger schema")

    @property
    def first_error(self) -> ExtractionEntry | None:
        """Return the first stable incomplete entry, if present."""
        return next(
            (entry for entry in self.entries if entry.state in _INCOMPLETE_STATES),
            None,
        )

    def count(self, state: BlockState) -> int:
        """Count entries in one state."""
        return sum(entry.state is state for entry in self.entries)


_VERIFIED_STATES: Final = frozenset(
    (BlockState.DECODED, BlockState.SUPPLEMENTED, BlockState.RAW_ONLY),
)
_INCOMPLETE_STATES: Final = frozenset(
    (BlockState.RAW_ONLY, BlockState.ENCRYPTED_BLOCKED, BlockState.DAMAGED),
)


def build_extraction_ledger(
    source_path: str,
    source_sha256: str,
    entries: Sequence[ExtractionEntry],
    *,
    warnings: Sequence[str] = (),
) -> ExtractionLedger:
    """Sort evidence deterministically and derive the documented map status."""
    ordered = tuple(sorted(entries, key=_entry_sort_key))
    return ExtractionLedger(
        source_path=source_path,
        source_sha256=source_sha256,
        status=_aggregate_status(ordered),
        entries=ordered,
        warnings=tuple(warnings),
    )


def _aggregate_status(entries: Sequence[ExtractionEntry]) -> ExtractionStatus:
    states = {entry.state for entry in entries}
    if BlockState.DAMAGED in states:
        return ExtractionStatus.DAMAGED
    if BlockState.RAW_ONLY in states:
        return ExtractionStatus.PARTIAL
    if BlockState.ENCRYPTED_BLOCKED in states:
        return ExtractionStatus.ENCRYPTED_BLOCKED
    return ExtractionStatus.COMPLETE


def _entry_sort_key(entry: ExtractionEntry) -> tuple[int, int, str]:
    missing_block = int(entry.block_index is None)
    block_index = entry.block_index if entry.block_index is not None else 0
    return missing_block, block_index, entry.internal_path.casefold()
