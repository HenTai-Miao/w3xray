"""Semantic invariants for parsed authoritative batch results."""

from __future__ import annotations

from typing import assert_never

from .batch_models import BatchStateFormatError, MapBatchResult
from .batch_status import (
    ArchiveIntegrity,
    BatchAxes,
    KnowledgeEvidence,
    PublicationResult,
    derive_batch_axes,
    derive_legacy_map_state,
)
from .icon_evidence_counts import physical_icon_failure_count
from .safe_output import safe_relative_path


def validate_result_state(result: MapBatchResult) -> None:
    """Reject published and terminal results with contradictory state."""
    if result.valid_icon_reference_count != (
        result.resolved_icon_reference_count + result.unresolved_icon_reference_count
    ):
        raise BatchStateFormatError(
            "valid icon reference count must equal resolved plus unresolved references"
        )
    if result.icon_failure_count != physical_icon_failure_count(
        result.anonymous_read_failure_count,
        result.original_write_failure_count,
        result.png_failure_count,
    ):
        raise BatchStateFormatError(
            "icon failure count must equal anonymous read plus original write plus PNG failures"
        )
    has_reasons = bool(result.knowledge_gap_reasons)
    if (result.knowledge_evidence is KnowledgeEvidence.PARTIAL) != has_reasons:
        raise BatchStateFormatError(
            "knowledge evidence must be partial exactly when reasons are present"
        )
    expected_archive = derive_batch_axes(
        result.publication_result,
        raw_blocks=result.raw_block_count,
        damaged_blocks=result.damaged_block_count,
        restricted_blocks=result.restricted_block_count,
        icon_gaps=0,
        current_text_states=(),
        relation_partial_count=0,
        unresolved_endpoint_count=0,
    ).archive
    if result.archive_integrity is not expected_archive:
        raise BatchStateFormatError("archive integrity disagrees with block counters")
    axes = BatchAxes(
        result.publication_result,
        result.archive_integrity,
        result.knowledge_evidence,
        result.knowledge_gap_reasons,
    )
    if result.state is not derive_legacy_map_state(axes):
        raise BatchStateFormatError("legacy state disagrees with authoritative axes")
    match result.publication_result:
        case PublicationResult.PUBLISHED:
            relative = safe_relative_path(result.output_directory)
            if (
                result.stage != "published"
                or relative is None
                or len(relative.parts) != 2
                or relative.parts[0] != "地图"
            ):
                raise BatchStateFormatError("published state has an unsafe stage/path")
            _require_digest(result.dependency_fingerprint, "dependency fingerprint")
            _require_digest(result.manifest_sha256, "manifest SHA-256")
        case PublicationResult.FAILED | PublicationResult.CANCELLED:
            if (
                not result.stage
                or result.stage == "published"
                or result.output_directory
                or result.manifest_sha256
                or result.published_bytes
            ):
                raise BatchStateFormatError("failed/cancelled state contradicts stage")
            if result.dependency_fingerprint:
                _require_digest(
                    result.dependency_fingerprint,
                    "dependency fingerprint",
                )
            if result.archive_integrity is not ArchiveIntegrity.COMPLETE:
                raise BatchStateFormatError(
                    "unpublished result cannot claim archive block evidence"
                )
        case unreachable:
            assert_never(unreachable)


def require_unique_results(results: tuple[MapBatchResult, ...]) -> None:
    """Reject aliased source and output identities."""
    paths: set[str] = set()
    identities: set[tuple[str, int]] = set()
    outputs: set[str] = set()
    for result in results:
        path_key = result.source.path.casefold()
        identity = result.source.sha256, result.source.size
        if path_key in paths or identity in identities:
            raise BatchStateFormatError("duplicate source result")
        paths.add(path_key)
        identities.add(identity)
        if result.output_directory:
            output_key = result.output_directory.casefold()
            if output_key in outputs:
                raise BatchStateFormatError("duplicate output directory")
            outputs.add(output_key)


def _require_digest(value: str, label: str) -> None:
    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise BatchStateFormatError(f"invalid {label}")
