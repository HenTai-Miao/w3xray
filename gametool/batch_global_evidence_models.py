"""Immutable deterministic records for batch-wide icon evidence."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import override

from .icon_evidence_models import (
    IconCandidateEvidence,
    IconDiagnosticFlag,
    IconGapReason,
    IconResolutionLayer,
)
from .icon_resources import IconObjectReference


class GlobalEvidenceError(ValueError):
    """Verified map evidence cannot be represented without ambiguity."""

    __slots__ = ("detail",)

    detail: str

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail

    @override
    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True, slots=True)
class GlobalIconGap:
    """One normalized unresolved path and its complete reference evidence."""

    map_path: str
    map_sha256: str
    map_scope: str
    normalized_path: str
    reason: IconGapReason
    diagnostics: tuple[IconDiagnosticFlag, ...]
    object_categories: tuple[str, ...]
    rawcodes: tuple[str, ...]
    references: tuple[IconObjectReference, ...]
    reference_count: int


@dataclass(frozen=True, slots=True)
class GlobalResolvedIcon:
    """One named payload retained with exact source-map provenance."""

    map_path: str
    map_sha256: str
    normalized_path: str
    layer: IconResolutionLayer
    content_sha256: str
    source_path: str


@dataclass(frozen=True, slots=True)
class GlobalAnonymousIcon:
    """One anonymous payload retained with its archive block identity."""

    map_path: str
    map_sha256: str
    block_index: int
    content_sha256: str
    source_path: str


@dataclass(frozen=True, slots=True)
class GlobalEvidenceIndex:
    """Sorted batch-wide evidence and explicitly non-authoritative candidates."""

    gaps: tuple[GlobalIconGap, ...]
    resolved: tuple[GlobalResolvedIcon, ...]
    anonymous: tuple[GlobalAnonymousIcon, ...]
    candidates: tuple[IconCandidateEvidence, ...]

    @classmethod
    def build(
        cls,
        gaps: Iterable[GlobalIconGap],
        resolved: Iterable[GlobalResolvedIcon],
        anonymous: Iterable[GlobalAnonymousIcon],
        candidates: Iterable[IconCandidateEvidence],
    ) -> GlobalEvidenceIndex:
        """Build one stable index independent of input traversal order."""
        return cls(
            tuple(sorted(gaps, key=_gap_key)),
            tuple(sorted(resolved, key=_resolved_key)),
            tuple(sorted(anonymous, key=_anonymous_key)),
            tuple(sorted(candidates, key=_candidate_key)),
        )


def _gap_key(row: GlobalIconGap) -> tuple[str, ...]:
    return (
        row.map_path.casefold(),
        row.map_path,
        row.map_sha256,
        row.normalized_path.casefold(),
        row.normalized_path,
        row.reason.value,
    )


def _resolved_key(row: GlobalResolvedIcon) -> tuple[str, ...]:
    return (
        row.map_path.casefold(),
        row.map_path,
        row.map_sha256,
        row.normalized_path.casefold(),
        row.normalized_path,
        row.layer.value,
        row.content_sha256,
        row.source_path.casefold(),
        row.source_path,
    )


def _anonymous_key(row: GlobalAnonymousIcon) -> tuple[str | int, ...]:
    return (
        row.map_path.casefold(),
        row.map_path,
        row.map_sha256,
        row.block_index,
        row.content_sha256,
        row.source_path.casefold(),
        row.source_path,
    )


def _candidate_key(row: IconCandidateEvidence) -> tuple[str | int, ...]:
    return (
        row.kind.value,
        row.requested_map_sha256,
        row.requested_path.casefold(),
        row.requested_path,
        row.anonymous_map_sha256,
        -1 if row.anonymous_block_index is None else row.anonymous_block_index,
        row.candidate_map_sha256,
        row.candidate_path.casefold(),
        row.candidate_path,
        row.content_sha256,
    )


__all__ = (
    "GlobalAnonymousIcon",
    "GlobalEvidenceIndex",
    "GlobalEvidenceError",
    "GlobalIconGap",
    "GlobalResolvedIcon",
)
