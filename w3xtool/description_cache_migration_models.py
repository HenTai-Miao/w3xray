"""Typed contracts for historical description-cache migration."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, unique
from pathlib import Path


@unique
class DescriptionCacheRejectionReason(StrEnum):
    """Stable reasons for rejecting one structurally valid legacy row."""

    INVALID_IDENTITY = "invalid_identity"
    NOT_BASE_OBJECT = "not_base_object"
    UNSUPPORTED_ROLE = "unsupported_role"
    SOURCE_MAP_UNKNOWN = "source_map_unknown"
    SOURCE_PATH_ESCAPE = "source_path_escape"
    SOURCE_REPORT_MISSING = "source_report_missing"
    SOURCE_ROW_MISSING = "source_row_missing"
    SOURCE_LABEL_MISMATCH = "source_label_mismatch"
    READABLE_MISMATCH = "readable_mismatch"
    TSV_ROUND_TRIP_MISMATCH = "tsv_round_trip_mismatch"
    CONFLICTING_VALUE = "conflicting_value"


@dataclass(frozen=True, slots=True)
class DescriptionCacheMigrationOptions:
    """Three explicit, non-overlapping migration paths."""

    legacy_output: Path
    legacy_cache: Path
    output: Path


@dataclass(frozen=True, slots=True)
class DescriptionCacheRejection:
    """One rejected legacy candidate with stable source coordinates."""

    row_number: int
    category: str
    base_id: str
    role: str
    level_text: str
    raw_value: str
    readable_value: str
    source_map_sha256: str
    source_path: str
    reason: DescriptionCacheRejectionReason
    detail: str


@dataclass(frozen=True, slots=True)
class DescriptionCacheMigrationResult:
    """Published migration counts and all deterministic rejections."""

    accepted_count: int
    rejected_count: int
    rejections: tuple[DescriptionCacheRejection, ...]
    output: Path


class DescriptionCacheMigrationError(OSError):
    """Untrusted migration input failed structural preflight.

    Exceptions retain Python-managed traceback state and therefore cannot be frozen.
    """

    __slots__ = ("detail",)

    detail: str

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True, slots=True)
class LegacyDescriptionCacheRow:
    """One structurally valid schema-2 candidate row."""

    row_number: int
    category: str
    base_id: str
    role: str
    level_text: str
    raw_value: str
    readable_value: str
    source_map_sha256: str
    source_path: str

    @property
    def cells(self) -> tuple[str, ...]:
        """Return exact decoded cells in historical column order."""
        return (
            self.category,
            self.base_id,
            self.role,
            self.level_text,
            self.raw_value,
            self.readable_value,
            self.source_map_sha256,
            self.source_path,
        )


@dataclass(frozen=True, slots=True)
class LegacyDescriptionReportRow:
    """One structurally valid row from an exact historical map report."""

    row_number: int
    cells: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LegacyStateResult:
    """The schema-1 fields required to bind a candidate to one report."""

    source_path: str
    source_sha256: str
    output_directory: str
    stage: str


@dataclass(frozen=True, slots=True)
class LegacySourceReport:
    """One stable, hash-bound historical report, or an explicit absence."""

    state: LegacyStateResult
    path: Path
    sha256: str | None
    rows: tuple[LegacyDescriptionReportRow, ...]


@dataclass(frozen=True, slots=True)
class ProvenDescriptionCandidate:
    """A candidate proven against one exact source report row."""

    candidate: LegacyDescriptionCacheRow
    level: int | None
    report_path: Path
    report_sha256: str
    report_row_number: int
    report_row_sha256: str
    source_label: str
