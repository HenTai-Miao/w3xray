"""Shared semantic validation for persisted schema-five batch evidence."""

from __future__ import annotations

from dataclasses import dataclass

from .batch_status import (
    ArchiveIntegrity,
    KnowledgeEvidence,
    KnowledgeGapReason,
    MapBatchState,
    PublicationResult,
    derive_batch_axes,
    derive_legacy_map_state,
)
from .icon_evidence_models import IconDiagnosticFlag
from .object_text_models import ObjectTextState


@dataclass(frozen=True, slots=True)
class BatchSemanticEvidence:
    """All persisted counters needed to prove schema-five axes and reasons."""

    publication: PublicationResult
    archive: ArchiveIntegrity
    knowledge: KnowledgeEvidence
    knowledge_reasons: tuple[KnowledgeGapReason, ...]
    state: MapBatchState
    raw_blocks: int
    damaged_blocks: int
    restricted_blocks: int
    valid_icon_references: int
    resolved_icon_references: int
    unresolved_icon_references: int
    unresolved_icons: int
    anonymous_read_failures: int
    original_write_failures: int
    png_failures: int
    icon_failures: int
    description_counts: tuple[tuple[str, int], ...]
    current_source_unavailable_count: int
    current_source_conflict_count: int
    relation_counts: tuple[tuple[str, int], ...]
    relation_incomplete_count: int
    relation_partial_count: int
    unresolved_endpoint_count: int
    client_unavailable_icon_count: int


def batch_semantics_error(evidence: BatchSemanticEvidence) -> str | None:
    """Return the first stable persisted-evidence contradiction, if any."""
    if evidence.valid_icon_references != (
        evidence.resolved_icon_references + evidence.unresolved_icon_references
    ):
        return (
            "valid icon reference count must equal resolved plus unresolved references"
        )
    if evidence.unresolved_icons > evidence.unresolved_icon_references:
        return "unresolved icon count exceeds unresolved icon reference count"
    if evidence.client_unavailable_icon_count > evidence.unresolved_icons:
        return "client unavailable icon count exceeds unresolved icon count"
    if evidence.icon_failures != (
        evidence.anonymous_read_failures
        + evidence.original_write_failures
        + evidence.png_failures
    ):
        return "icon failure count must equal anonymous read plus original write plus PNG failures"
    if (
        evidence.relation_partial_count + evidence.unresolved_endpoint_count
        != evidence.relation_incomplete_count
    ):
        return "relation evidence counts disagree with relation incomplete count"
    if evidence.relation_incomplete_count > sum(
        count for _label, count in evidence.relation_counts
    ):
        return "relation incomplete count exceeds relation count"
    if evidence.current_source_unavailable_count > _description_count(
        evidence.description_counts,
        ObjectTextState.SOURCE_UNAVAILABLE,
    ) or evidence.current_source_conflict_count > _description_count(
        evidence.description_counts,
        ObjectTextState.SOURCE_CONFLICT,
    ):
        return "current text evidence exceeds description counts"
    expected = derive_batch_axes(
        evidence.publication,
        raw_blocks=evidence.raw_blocks,
        damaged_blocks=evidence.damaged_blocks,
        restricted_blocks=evidence.restricted_blocks,
        icon_gaps=evidence.unresolved_icons,
        current_text_states=_current_text_states(evidence),
        relation_partial_count=evidence.relation_partial_count,
        unresolved_endpoint_count=evidence.unresolved_endpoint_count,
        icon_diagnostics=_icon_diagnostics(evidence),
    )
    if evidence.archive is not expected.archive:
        return "archive integrity disagrees with block counters"
    if evidence.knowledge_reasons != expected.knowledge_reasons:
        return "knowledge gap reasons disagree with persisted evidence"
    if evidence.knowledge is not expected.knowledge:
        return "knowledge evidence disagrees with persisted evidence"
    if evidence.state is not derive_legacy_map_state(expected):
        return "legacy state disagrees with authoritative axes"
    return None


def _description_count(
    counts: tuple[tuple[str, int], ...],
    state: ObjectTextState,
) -> int:
    """Return one persisted complete-text state count, or zero when absent."""
    return next((count for label, count in counts if label == state.value), 0)


def _current_text_states(
    evidence: BatchSemanticEvidence,
) -> tuple[ObjectTextState, ...]:
    """Rebuild only persisted current text evidence relevant to status."""
    unavailable = (
        (ObjectTextState.SOURCE_UNAVAILABLE,)
        if evidence.current_source_unavailable_count > 0
        else ()
    )
    conflict = (
        (ObjectTextState.SOURCE_CONFLICT,)
        if evidence.current_source_conflict_count > 0
        else ()
    )
    return unavailable + conflict


def _icon_diagnostics(
    evidence: BatchSemanticEvidence,
) -> tuple[IconDiagnosticFlag, ...]:
    """Rebuild the persisted client-source availability diagnostic."""
    if evidence.client_unavailable_icon_count > 0:
        return (IconDiagnosticFlag.CLIENT_NOT_PROVIDED,)
    return ()


__all__ = ("BatchSemanticEvidence", "batch_semantics_error")
