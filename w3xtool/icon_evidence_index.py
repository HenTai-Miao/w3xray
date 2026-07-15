"""Build deterministic immutable indexes over icon evidence models."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from .icon_evidence_models import (
    FilteredIconEvidence,
    IconCandidateEvidence,
    IconLookupAttempt,
    ResolvedIconEvidence,
    UnresolvedIconEvidence,
)

if TYPE_CHECKING:
    from .icon_resources import AnonymousIconResource, IconObjectReference

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
        (
            IconCandidateEvidence(
                row.kind,
                row.requested_map_sha256,
                row.requested_path,
                row.anonymous_map_sha256,
                row.anonymous_block_index,
                row.candidate_map_sha256,
                row.candidate_path,
                row.content_sha256,
            )
            for index in items
            for row in index.candidates
        ),
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
) -> tuple[
    tuple[str, ...],
    str,
    str,
    str,
    str,
    str,
    str,
    bytes,
    tuple[tuple[str, ...], ...],
]:
    return (
        _reference_key(row.reference),
        row.layer.value,
        row.resolved_path.casefold(),
        row.resolved_path,
        row.content_sha256,
        row.source_path.casefold(),
        row.source_path,
        row.payload,
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
) -> tuple[str, str, int, str, str, str, str, str, bytes, None]:
    return (
        row.source_path.casefold(),
        row.source_path,
        row.block_index,
        row.sha256,
        row.basename.casefold(),
        row.basename,
        row.ledger_source.value,
        row.ledger_state.value,
        row.payload,
        row.original_path,
    )


def _candidate_key(
    row: IconCandidateEvidence,
) -> tuple[str, str, str, str, str, int, int, str, str, str, str, int]:
    return (
        row.requested_map_sha256,
        row.requested_path.casefold(),
        row.requested_path,
        row.kind.value,
        row.anonymous_map_sha256,
        int(row.anonymous_block_index is not None),
        0 if row.anonymous_block_index is None else row.anonymous_block_index,
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
