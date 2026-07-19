"""Independent publication, archive, and knowledge-axis contracts."""

from __future__ import annotations

from w3xtool.batch_status import (
    ArchiveIntegrity,
    KnowledgeEvidence,
    KnowledgeGapReason,
    PublicationResult,
    derive_batch_axes,
    derive_legacy_map_state,
)
from w3xtool.batch_models import MapBatchState
from w3xtool.object_text_models import ObjectTextState


def test_published_map_with_icon_gap_is_not_a_publication_failure() -> None:
    # Given / When
    axes = derive_batch_axes(
        publication=PublicationResult.PUBLISHED,
        raw_blocks=0,
        damaged_blocks=0,
        restricted_blocks=0,
        icon_gaps=1,
        current_text_states=(),
        relation_partial_count=0,
        unresolved_endpoint_count=0,
    )

    # Then
    assert axes.publication is PublicationResult.PUBLISHED
    assert axes.archive is ArchiveIntegrity.COMPLETE
    assert axes.knowledge is KnowledgeEvidence.PARTIAL
    assert axes.knowledge_reasons == (KnowledgeGapReason.ICON_UNBOUND,)
    assert derive_legacy_map_state(axes) is MapBatchState.PARTIAL


def test_archive_damage_does_not_change_knowledge_axis() -> None:
    # Given / When
    axes = derive_batch_axes(
        publication=PublicationResult.PUBLISHED,
        raw_blocks=0,
        damaged_blocks=3,
        restricted_blocks=0,
        icon_gaps=0,
        current_text_states=(ObjectTextState.MAP_VALUE,),
        relation_partial_count=0,
        unresolved_endpoint_count=0,
    )

    # Then
    assert axes.archive is ArchiveIntegrity.DAMAGED_BLOCKS
    assert axes.knowledge is KnowledgeEvidence.COMPLETE


def test_missing_substantive_source_coverage_is_knowledge_partial() -> None:
    # Given / When: publication succeeds without any analysis-bearing source.
    axes = derive_batch_axes(
        publication=PublicationResult.PUBLISHED,
        raw_blocks=0,
        damaged_blocks=0,
        restricted_blocks=0,
        icon_gaps=0,
        current_text_states=(),
        relation_partial_count=0,
        unresolved_endpoint_count=0,
        source_coverage_gap_count=1,
    )

    # Then: absence of observable gaps cannot be promoted to complete knowledge.
    assert axes.publication is PublicationResult.PUBLISHED
    assert axes.archive is ArchiveIntegrity.COMPLETE
    assert axes.knowledge is KnowledgeEvidence.PARTIAL
    assert axes.knowledge_reasons == (KnowledgeGapReason.SOURCE_COVERAGE_MISSING,)
    assert derive_legacy_map_state(axes) is MapBatchState.PARTIAL
