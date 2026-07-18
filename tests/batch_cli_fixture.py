"""Schema-five batch-result fixture for batch CLI outcome tests."""

from __future__ import annotations

from typing import assert_never

from w3xtool.batch_models import MapBatchResult, MapBatchState, SourceFingerprint
from w3xtool.batch_status import PublicationResult, derive_batch_axes


def batch_cli_result(state: MapBatchState) -> MapBatchResult:
    """Build the exact terminal or published result used by CLI tests."""
    match state:
        case MapBatchState.COMPLETE:
            publication, raw_blocks, restricted_blocks = (
                PublicationResult.PUBLISHED,
                0,
                0,
            )
        case MapBatchState.PARTIAL:
            publication, raw_blocks, restricted_blocks = (
                PublicationResult.PUBLISHED,
                1,
                0,
            )
        case MapBatchState.RESTRICTED:
            publication, raw_blocks, restricted_blocks = (
                PublicationResult.PUBLISHED,
                0,
                1,
            )
        case MapBatchState.FAILED:
            publication, raw_blocks, restricted_blocks = (
                PublicationResult.FAILED,
                0,
                0,
            )
        case MapBatchState.CANCELLED:
            publication, raw_blocks, restricted_blocks = (
                PublicationResult.CANCELLED,
                0,
                0,
            )
        case unreachable:
            assert_never(unreachable)
    terminal = publication is not PublicationResult.PUBLISHED
    axes = derive_batch_axes(
        publication,
        raw_blocks=raw_blocks,
        damaged_blocks=0,
        restricted_blocks=restricted_blocks,
        icon_gaps=0,
        current_text_states=(),
        relation_partial_count=0,
        unresolved_endpoint_count=0,
    )
    return MapBatchResult(
        source=SourceFingerprint("/maps/a.w3x", 10, 20, "a" * 64),
        display_name="A",
        output_directory="" if terminal else "地图/001_A_aaaaaaaa",
        stage="load/process" if terminal else "published",
        state=state,
        first_error="broken" if terminal else "",
        object_count=1,
        description_counts=(),
        named_icon_count=1,
        anonymous_icon_count=0,
        original_written_count=1,
        png_written_count=1,
        icon_failure_count=0,
        restricted_block_count=restricted_blocks,
        elapsed_ms=1,
        publication_result=axes.publication,
        archive_integrity=axes.archive,
        knowledge_evidence=axes.knowledge,
        knowledge_gap_reasons=axes.knowledge_reasons,
        raw_block_count=raw_blocks,
        damaged_block_count=0,
        valid_icon_reference_count=0,
        resolved_icon_reference_count=0,
        filtered_icon_field_count=0,
        unresolved_icon_count=0,
        unresolved_icon_reference_count=0,
        anonymous_read_failure_count=0,
        original_write_failure_count=0,
        png_failure_count=0,
    )
