"""Typed authoritative-axis fields for batch-result test fixtures."""

from __future__ import annotations

from typing import TypedDict, assert_never

from w3xtool.batch_models import MapBatchState
from w3xtool.batch_status import (
    ArchiveIntegrity,
    BatchAxes,
    KnowledgeEvidence,
    KnowledgeGapReason,
    PublicationResult,
    derive_batch_axes,
)


class AxisFields(TypedDict):
    """MapBatchResult replacement fields derived from one legacy state."""

    state: MapBatchState
    publication_result: PublicationResult
    archive_integrity: ArchiveIntegrity
    knowledge_evidence: KnowledgeEvidence
    knowledge_gap_reasons: tuple[KnowledgeGapReason, ...]
    raw_block_count: int
    restricted_block_count: int


def axis_fields(state: MapBatchState) -> AxisFields:
    """Return the authoritative axes and matching block counters for one state."""
    axes, raw_blocks, restricted_blocks = _axes_for_state(state)
    return {
        "state": state,
        "publication_result": axes.publication,
        "archive_integrity": axes.archive,
        "knowledge_evidence": axes.knowledge,
        "knowledge_gap_reasons": axes.knowledge_reasons,
        "raw_block_count": raw_blocks,
        "restricted_block_count": restricted_blocks,
    }


def _axes_for_state(state: MapBatchState) -> tuple[BatchAxes, int, int]:
    match state:
        case MapBatchState.COMPLETE:
            return _published_axes(), 0, 0
        case MapBatchState.PARTIAL:
            return _published_axes(raw_blocks=1), 1, 0
        case MapBatchState.RESTRICTED:
            return _published_axes(restricted_blocks=1), 0, 1
        case MapBatchState.FAILED:
            return _terminal_axes(PublicationResult.FAILED), 0, 0
        case MapBatchState.CANCELLED:
            return _terminal_axes(PublicationResult.CANCELLED), 0, 0
        case unreachable:
            assert_never(unreachable)


def _published_axes(*, raw_blocks: int = 0, restricted_blocks: int = 0) -> BatchAxes:
    return derive_batch_axes(
        PublicationResult.PUBLISHED,
        raw_blocks=raw_blocks,
        damaged_blocks=0,
        restricted_blocks=restricted_blocks,
        icon_gaps=0,
        current_text_states=(),
        relation_partial_count=0,
        unresolved_endpoint_count=0,
    )


def _terminal_axes(publication: PublicationResult) -> BatchAxes:
    return derive_batch_axes(
        publication,
        raw_blocks=0,
        damaged_blocks=0,
        restricted_blocks=0,
        icon_gaps=0,
        current_text_states=(),
        relation_partial_count=0,
        unresolved_endpoint_count=0,
    )
