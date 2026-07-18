"""Semantic invariants for persisted per-map publication summaries."""

from __future__ import annotations

from typing import assert_never

from .batch_manifest_models import BatchManifestFormatError, ManifestResultSummary
from .batch_status import (
    BatchSemanticEvidence,
    PublicationResult,
    batch_semantics_error,
)


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
    error = batch_semantics_error(
        BatchSemanticEvidence(
            summary.publication_result,
            summary.archive_integrity,
            summary.knowledge_evidence,
            summary.knowledge_gap_reasons,
            summary.state,
            summary.raw_block_count,
            summary.damaged_block_count,
            summary.restricted_block_count,
            summary.valid_icon_reference_count,
            summary.resolved_icon_reference_count,
            summary.unresolved_icon_reference_count,
            summary.unresolved_icon_count,
            summary.anonymous_read_failure_count,
            summary.original_write_failure_count,
            summary.png_failure_count,
            summary.icon_failure_count,
            summary.current_source_unavailable_count,
            summary.current_source_conflict_count,
            summary.relation_partial_count,
            summary.unresolved_endpoint_count,
            summary.client_unavailable_icon_count,
        )
    )
    if error is not None:
        raise BatchManifestFormatError(error)


__all__ = ("validate_manifest_summary",)
