"""Immutable state models shared by batch extraction and reporting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from .batch_status import (
    ArchiveIntegrity,
    KnowledgeEvidence,
    KnowledgeGapReason,
    MapBatchState,
    PublicationResult,
)

BATCH_SCHEMA_VERSION: Final = 5


class BatchStateFormatError(ValueError):
    """Reject malformed or incompatible persisted batch state."""

    __slots__ = ("detail",)

    detail: str

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True, slots=True)
class SourceFingerprint:
    path: str
    size: int
    mtime_ns: int
    sha256: str


@dataclass(frozen=True, slots=True)
class MapBatchResult:
    source: SourceFingerprint
    display_name: str
    output_directory: str
    stage: str
    state: MapBatchState
    first_error: str
    object_count: int
    description_counts: tuple[tuple[str, int], ...]
    named_icon_count: int
    anonymous_icon_count: int
    original_written_count: int
    png_written_count: int
    icon_failure_count: int
    restricted_block_count: int
    elapsed_ms: int
    publication_result: PublicationResult
    archive_integrity: ArchiveIntegrity
    knowledge_evidence: KnowledgeEvidence
    knowledge_gap_reasons: tuple[KnowledgeGapReason, ...]
    raw_block_count: int
    damaged_block_count: int
    valid_icon_reference_count: int
    resolved_icon_reference_count: int
    filtered_icon_field_count: int
    unresolved_icon_count: int
    unresolved_icon_reference_count: int
    anonymous_read_failure_count: int
    original_write_failure_count: int
    png_failure_count: int
    relation_counts: tuple[tuple[str, int], ...] = ()
    relation_incomplete_count: int = 0
    dependency_fingerprint: str = ""
    manifest_sha256: str = ""
    published_bytes: int = 0
    peak_rss_bytes: int = 0


@dataclass(frozen=True, slots=True)
class BatchState:
    schema_version: int
    results: tuple[MapBatchResult, ...]

    def __post_init__(self) -> None:
        if self.schema_version != BATCH_SCHEMA_VERSION:
            raise BatchStateFormatError("unsupported batch state schema")
