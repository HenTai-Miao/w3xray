"""Closed immutable variants for auditable icon resolution evidence."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING

from .icon_field_evidence import IconFieldDisposition

if TYPE_CHECKING:
    from .icon_resources import (
        AnonymousIconResource,
        IconObjectReference,
        NamedIconArchive,
    )


class IconGapReason(StrEnum):
    """Primary reason an eligible icon reference remains unresolved."""

    INVALID_REFERENCE = "invalid_reference"
    NAMED_RESOURCE_MISSING = "named_resource_missing"
    ANONYMOUS_PAYLOAD_UNBOUND = "anonymous_payload_unbound"
    CLIENT_SOURCE_UNAVAILABLE = "client_source_unavailable"
    HISTORICAL_CLIENT_MISS = "historical_client_miss"
    ARCHIVE_NAME_UNAVAILABLE = "archive_name_unavailable"
    ARCHIVE_BLOCK_DAMAGED = "archive_block_damaged"


class IconDiagnosticFlag(StrEnum):
    """Independent static facts retained beside the primary gap reason."""

    CLIENT_NOT_PROVIDED = "client_not_provided"
    HISTORICAL_EVIDENCE_CHECKED = "historical_evidence_checked"
    ANONYMOUS_BLP_PRESENT = "anonymous_blp_present"
    ARCHIVE_HAS_RAW_BLOCK = "archive_has_raw_block"
    ARCHIVE_HAS_DAMAGED_BLOCK = "archive_has_damaged_block"
    ARCHIVE_HAS_RESTRICTED_BLOCK = "archive_has_restricted_block"


class IconResolutionLayer(StrEnum):
    """Strict lookup layers in documented precedence order."""

    CURRENT_MAP = "current_map"
    CAMPAIGN_ROOT = "campaign_root"
    CLIENT = "client"
    SAME_MAP_HISTORY = "same_map_history"
    TRUSTED_CACHE = "trusted_cache"


@dataclass(frozen=True, slots=True)
class IconArchiveLayer:
    """One exact named archive and its logical provenance."""

    layer: IconResolutionLayer
    archive: NamedIconArchive
    source_path: str


@dataclass(frozen=True, slots=True)
class IconLookupAttempt:
    """One exact candidate lookup with structured outcome evidence."""

    layer: IconResolutionLayer
    candidate_path: str
    source_path: str
    found: bool
    resolved_path: str = ""
    content_sha256: str = ""


@dataclass(frozen=True, slots=True)
class ResolvedIconEvidence:
    """An eligible reference bound to hash-verified bytes."""

    reference: IconObjectReference
    resolved_path: str
    source_path: str
    payload: bytes
    content_sha256: str
    layer: IconResolutionLayer
    attempts: tuple[IconLookupAttempt, ...]


@dataclass(frozen=True, slots=True)
class UnresolvedIconEvidence:
    """An eligible reference with a stable primary gap reason."""

    reference: IconObjectReference
    reason: IconGapReason
    diagnostics: tuple[IconDiagnosticFlag, ...]
    attempts: tuple[IconLookupAttempt, ...]

    def __post_init__(self) -> None:
        ordered = tuple(sorted(set(self.diagnostics), key=lambda flag: flag.value))
        if ordered != self.diagnostics:
            object.__setattr__(self, "diagnostics", ordered)


@dataclass(frozen=True, slots=True)
class FilteredIconEvidence:
    """An exact false-icon field excluded before path lookup."""

    reference: IconObjectReference
    reason: IconFieldDisposition = IconFieldDisposition.FILTERED_NON_ICON


class IconCandidateKind(StrEnum):
    """Non-authoritative batch-wide candidate evidence kinds."""

    EXACT_OTHER_MAP_PATH = "exact_other_map_path"
    ANONYMOUS_HASH_MATCH = "anonymous_hash_match"


@dataclass(frozen=True, slots=True)
class IconCandidateEvidence:
    """A non-adopted hint retained without changing resolution state."""

    kind: IconCandidateKind
    requested_map_sha256: str
    requested_path: str
    anonymous_map_sha256: str
    anonymous_block_index: int | None
    candidate_map_sha256: str
    candidate_path: str
    content_sha256: str
    adopted: bool = False


type IconEvidenceRow = (
    ResolvedIconEvidence | UnresolvedIconEvidence | FilteredIconEvidence
)


@dataclass(frozen=True, slots=True)
class IconEvidenceIndex:
    """Deterministically ordered immutable icon evidence."""

    resolved: tuple[ResolvedIconEvidence, ...]
    unresolved: tuple[UnresolvedIconEvidence, ...]
    filtered: tuple[FilteredIconEvidence, ...]
    anonymous: tuple[AnonymousIconResource, ...]
    anonymous_read_failure_count: int
    candidates: tuple[IconCandidateEvidence, ...]
    _by_object: Mapping[tuple[str, str], tuple[IconEvidenceRow, ...]]

    @classmethod
    def build(
        cls,
        resolved: Iterable[ResolvedIconEvidence] = (),
        unresolved: Iterable[UnresolvedIconEvidence] = (),
        filtered: Iterable[FilteredIconEvidence] = (),
        anonymous: Iterable[AnonymousIconResource] = (),
        anonymous_read_failure_count: int = 0,
        candidates: Iterable[IconCandidateEvidence] = (),
    ) -> IconEvidenceIndex:
        """Freeze each evidence family in stable primitive-key order."""
        ordered_resolved = tuple(sorted(resolved, key=_resolved_key))
        ordered_unresolved = tuple(sorted(unresolved, key=_unresolved_key))
        ordered_filtered = tuple(sorted(filtered, key=_filtered_key))
        ordered_anonymous = tuple(sorted(anonymous, key=_anonymous_key))
        ordered_candidates = tuple(sorted(candidates, key=_candidate_key))
        grouped: dict[tuple[str, str], list[IconEvidenceRow]] = {}
        for row in (*ordered_resolved, *ordered_unresolved, *ordered_filtered):
            reference = row.reference
            grouped.setdefault((reference.category, reference.object_id), []).append(
                row
            )
        return cls(
            ordered_resolved,
            ordered_unresolved,
            ordered_filtered,
            ordered_anonymous,
            anonymous_read_failure_count,
            ordered_candidates,
            MappingProxyType(
                {identity: tuple(rows) for identity, rows in grouped.items()}
            ),
        )

    def for_object(self, category: str, object_id: str) -> tuple[IconEvidenceRow, ...]:
        """Return rows for one exact category/rawcode identity."""
        return self._by_object.get((category, object_id), ())


def empty_icon_evidence_index() -> IconEvidenceIndex:
    """Return an empty immutable evidence index."""
    return IconEvidenceIndex.build()


def merge_icon_evidence_indexes(
    indexes: Iterable[IconEvidenceIndex],
) -> IconEvidenceIndex:
    """Rebuild one immutable aggregate from per-map indexes."""
    items = tuple(indexes)
    return IconEvidenceIndex.build(
        (row for index in items for row in index.resolved),
        (row for index in items for row in index.unresolved),
        (row for index in items for row in index.filtered),
        (row for index in items for row in index.anonymous),
        sum(index.anonymous_read_failure_count for index in items),
        (row for index in items for row in index.candidates),
    )


def _reference_key(reference: IconObjectReference) -> tuple[str, ...]:
    ordered_text = (
        reference.map_path,
        reference.map_scope,
        reference.category,
        reference.object_id,
        reference.object_name,
        reference.base_id,
        reference.field_key,
        reference.field_label,
        reference.field_type,
        reference.field_source,
        reference.wts_source,
        reference.normalized_path,
        reference.requested_path,
    )
    return (
        reference.map_sha256,
        *(part for value in ordered_text for part in (value.casefold(), value)),
    )


def _resolved_key(
    row: ResolvedIconEvidence,
) -> tuple[tuple[str, ...], str, str, str, str, str, tuple[tuple[str, ...], ...]]:
    return (
        _reference_key(row.reference),
        row.layer.value,
        row.resolved_path.casefold(),
        row.resolved_path,
        row.content_sha256,
        row.source_path.casefold(),
        _attempts_key(row.attempts),
    )


def _unresolved_key(
    row: UnresolvedIconEvidence,
) -> tuple[tuple[str, ...], str, tuple[str, ...], tuple[tuple[str, ...], ...]]:
    return (
        _reference_key(row.reference),
        row.reason.value,
        tuple(flag.value for flag in row.diagnostics),
        _attempts_key(row.attempts),
    )


def _filtered_key(row: FilteredIconEvidence) -> tuple[tuple[str, ...], str]:
    return _reference_key(row.reference), row.reason.value


def _anonymous_key(
    row: AnonymousIconResource,
) -> tuple[str, str, int, str, str, str, str, str]:
    return (
        row.source_path.casefold(),
        row.source_path,
        row.block_index,
        row.sha256,
        row.basename.casefold(),
        row.basename,
        row.ledger_source.value,
        row.ledger_state.value,
    )


def _candidate_key(
    row: IconCandidateEvidence,
) -> tuple[str, str, str, str, str, int, str, str, str, str, int]:
    return (
        row.requested_map_sha256,
        row.requested_path.casefold(),
        row.requested_path,
        row.kind.value,
        row.anonymous_map_sha256,
        -1 if row.anonymous_block_index is None else row.anonymous_block_index,
        row.candidate_map_sha256,
        row.candidate_path.casefold(),
        row.candidate_path,
        row.content_sha256,
        int(row.adopted),
    )


def _attempts_key(
    attempts: tuple[IconLookupAttempt, ...],
) -> tuple[tuple[str, ...], ...]:
    return tuple(
        (
            attempt.layer.value,
            attempt.candidate_path.casefold(),
            attempt.candidate_path,
            attempt.source_path.casefold(),
            attempt.source_path,
            str(int(attempt.found)),
            attempt.resolved_path,
            attempt.content_sha256,
        )
        for attempt in attempts
    )
