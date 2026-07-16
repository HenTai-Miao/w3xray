"""Semantic invariants for parsed authoritative batch results."""

from __future__ import annotations

from typing import assert_never

from .batch_models import BatchStateFormatError, MapBatchResult, MapBatchState
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
    match result.state:
        case MapBatchState.COMPLETE | MapBatchState.PARTIAL | MapBatchState.RESTRICTED:
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
        case MapBatchState.FAILED | MapBatchState.CANCELLED:
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
