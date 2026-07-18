"""Semantic invariants for parsed authoritative batch results."""

from __future__ import annotations

from typing import assert_never

from .batch_models import BatchStateFormatError, MapBatchResult
from .batch_status import (
    ArchiveIntegrity,
    BatchSemanticEvidence,
    PublicationResult,
    batch_semantics_error,
)
from .safe_output import safe_relative_path


def validate_result_state(result: MapBatchResult) -> None:
    """Reject published and terminal results with contradictory state."""
    error = batch_semantics_error(
        BatchSemanticEvidence(
            result.publication_result,
            result.archive_integrity,
            result.knowledge_evidence,
            result.knowledge_gap_reasons,
            result.state,
            result.raw_block_count,
            result.damaged_block_count,
            result.restricted_block_count,
            result.valid_icon_reference_count,
            result.resolved_icon_reference_count,
            result.unresolved_icon_reference_count,
            result.unresolved_icon_count,
            result.anonymous_read_failure_count,
            result.original_write_failure_count,
            result.png_failure_count,
            result.icon_failure_count,
            result.current_source_unavailable_count,
            result.current_source_conflict_count,
            result.relation_partial_count,
            result.unresolved_endpoint_count,
            result.client_unavailable_icon_count,
        )
    )
    if error is not None:
        raise BatchStateFormatError(error)
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
