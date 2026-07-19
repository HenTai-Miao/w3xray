"""Semantic invariants for persisted per-map publication summaries."""

from __future__ import annotations

from typing import assert_never

from .batch_manifest_models import BatchManifestFormatError, ManifestResultSummary
from .batch_semantic_validation import BatchSemanticEvidence, batch_semantics_error
from .batch_status import PublicationResult


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
            publication=summary.publication_result,
            archive=summary.archive_integrity,
            knowledge=summary.knowledge_evidence,
            knowledge_reasons=summary.knowledge_gap_reasons,
            state=summary.state,
            raw_blocks=summary.raw_block_count,
            damaged_blocks=summary.damaged_block_count,
            restricted_blocks=summary.restricted_block_count,
            valid_icon_references=summary.valid_icon_reference_count,
            resolved_icon_references=summary.resolved_icon_reference_count,
            unresolved_icon_references=summary.unresolved_icon_reference_count,
            unresolved_icons=summary.unresolved_icon_count,
            anonymous_read_failures=summary.anonymous_read_failure_count,
            original_write_failures=summary.original_write_failure_count,
            png_failures=summary.png_failure_count,
            icon_failures=summary.icon_failure_count,
            description_counts=summary.description_counts,
            current_source_unavailable_count=summary.current_source_unavailable_count,
            current_source_conflict_count=summary.current_source_conflict_count,
            relation_counts=summary.relation_counts,
            relation_incomplete_count=summary.relation_incomplete_count,
            relation_partial_count=summary.relation_partial_count,
            unresolved_endpoint_count=summary.unresolved_endpoint_count,
            client_unavailable_icon_count=summary.client_unavailable_icon_count,
            source_coverage_gap_count=summary.source_coverage_gap_count,
        )
    )
    if error is not None:
        raise BatchManifestFormatError(error)


__all__ = ("validate_manifest_summary",)
