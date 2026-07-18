"""Semantic invariants for persisted per-map publication summaries."""

from __future__ import annotations

from typing import assert_never

from .batch_manifest_models import BatchManifestFormatError, ManifestResultSummary
from .batch_status import (
    BatchAxes,
    KnowledgeEvidence,
    PublicationResult,
    derive_batch_axes,
    derive_legacy_map_state,
)
from .icon_evidence_counts import physical_icon_failure_count


def validate_manifest_summary(summary: ManifestResultSummary) -> None:
    """Reject a manifest summary that cannot describe one publication."""
    match summary.publication_result:
        case PublicationResult.PUBLISHED:
            pass
        case PublicationResult.FAILED | PublicationResult.CANCELLED:
            raise BatchManifestFormatError("manifest result is not published")
        case unreachable:
            assert_never(unreachable)
    if summary.stage != "published":
        raise BatchManifestFormatError("manifest result stage is not published")
    if summary.valid_icon_reference_count != (
        summary.resolved_icon_reference_count
        + summary.unresolved_icon_reference_count
    ):
        raise BatchManifestFormatError(
            "valid icon reference count must equal resolved plus unresolved references"
        )
    if summary.icon_failure_count != physical_icon_failure_count(
        summary.anonymous_read_failure_count,
        summary.original_write_failure_count,
        summary.png_failure_count,
    ):
        raise BatchManifestFormatError(
            "icon failure count must equal anonymous read plus original write plus PNG failures"
        )
    has_reasons = bool(summary.knowledge_gap_reasons)
    if (summary.knowledge_evidence is KnowledgeEvidence.PARTIAL) != has_reasons:
        raise BatchManifestFormatError(
            "knowledge evidence must be partial exactly when reasons are present"
        )
    expected_archive = derive_batch_axes(
        summary.publication_result,
        raw_blocks=summary.raw_block_count,
        damaged_blocks=summary.damaged_block_count,
        restricted_blocks=summary.restricted_block_count,
        icon_gaps=0,
        current_text_states=(),
        relation_partial_count=0,
        unresolved_endpoint_count=0,
    ).archive
    if summary.archive_integrity is not expected_archive:
        raise BatchManifestFormatError("archive integrity disagrees with block counters")
    axes = BatchAxes(
        summary.publication_result,
        summary.archive_integrity,
        summary.knowledge_evidence,
        summary.knowledge_gap_reasons,
    )
    if summary.state is not derive_legacy_map_state(axes):
        raise BatchManifestFormatError("legacy state disagrees with authoritative axes")


__all__ = ("validate_manifest_summary",)
