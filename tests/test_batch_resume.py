"""Manifest-verified resume and lossless checkpoint contracts."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from tests.batch_publication_fixture import empty_result, write_empty_publication
from w3xtool.batch_manifest_models import CONTENT_MANIFEST_NAME
from w3xtool.batch_models import (
    BATCH_SCHEMA_VERSION,
    BatchState,
    MapBatchResult,
    MapBatchState,
    SourceFingerprint,
)
from w3xtool.batch_resume import (
    PreviousBatchState,
    checkpoint_state,
    find_reusable_result,
)
from w3xtool.batch_status import BatchAxes, PublicationResult, derive_batch_axes


@pytest.mark.parametrize(
    "state",
    (MapBatchState.COMPLETE, MapBatchState.PARTIAL, MapBatchState.RESTRICTED),
)
def test_unchanged_manifest_verified_publication_is_reused(
    tmp_path: Path,
    state: MapBatchState,
) -> None:
    # Given
    dependency = "d" * 64
    result = _publish_valid_result(tmp_path, "a", state, dependency)
    previous = PreviousBatchState(
        BatchState(BATCH_SCHEMA_VERSION, (result,)),
        (),
    )

    # When
    decision = find_reusable_result(
        previous,
        result.source,
        dependency,
        str(tmp_path),
        retry_failed=True,
    )

    # Then
    assert decision.result == result
    assert decision.code == "reused_verified_publication"


def test_checkpoint_preserves_unvisited_previous_results() -> None:
    # Given
    previous = PreviousBatchState(
        BatchState(
            BATCH_SCHEMA_VERSION,
            (_result("a"), _result("b"), _result("c")),
        ),
        (),
    )
    current = (_result("a", state=MapBatchState.FAILED),)

    # When
    checkpoint = checkpoint_state(current, previous, ("/maps/b", "/maps/c"))

    # Then
    assert [Path(item.source.path).name for item in checkpoint.results] == [
        "a",
        "b",
        "c",
    ]


def test_dependency_change_forces_reprocessing(tmp_path: Path) -> None:
    # Given
    result = _publish_valid_result(
        tmp_path,
        "a",
        MapBatchState.PARTIAL,
        "d" * 64,
    )
    previous = _previous(result)

    # When
    decision = find_reusable_result(
        previous,
        result.source,
        "e" * 64,
        str(tmp_path),
        retry_failed=True,
    )

    # Then
    assert decision.result is None
    assert decision.code == "dependency_changed"


def test_reuse_selection_uses_authoritative_publication_result(
    tmp_path: Path,
) -> None:
    # Given: publication is authoritative even if a compatibility value drifts.
    dependency = "d" * 64
    result = _publish_valid_result(
        tmp_path,
        "a",
        MapBatchState.PARTIAL,
        dependency,
    )

    # When
    decision = find_reusable_result(
        _previous(result),
        result.source,
        dependency,
        str(tmp_path),
        retry_failed=True,
    )

    # Then
    assert decision.result == result
    assert decision.code == "reused_verified_publication"


def test_same_size_artifact_tampering_forces_reprocessing(tmp_path: Path) -> None:
    # Given
    result = _publish_valid_result(
        tmp_path,
        "a",
        MapBatchState.COMPLETE,
        "d" * 64,
    )
    report = tmp_path / result.output_directory / "地图摘要.txt"
    report.write_bytes(b"X" * report.stat().st_size)

    # When
    decision = find_reusable_result(
        _previous(result),
        result.source,
        result.dependency_fingerprint,
        str(tmp_path),
        retry_failed=True,
    )

    # Then
    assert decision.result is None
    assert decision.code == "publication_invalid"
    assert decision.detail == "artifact_hash_mismatch"


def test_missing_manifest_forces_reprocessing(tmp_path: Path) -> None:
    # Given
    result = _publish_valid_result(
        tmp_path,
        "a",
        MapBatchState.COMPLETE,
        "d" * 64,
    )
    (tmp_path / result.output_directory / CONTENT_MANIFEST_NAME).unlink()

    # When
    decision = find_reusable_result(
        _previous(result),
        result.source,
        result.dependency_fingerprint,
        str(tmp_path),
        retry_failed=True,
    )

    # Then
    assert decision.result is None
    assert decision.detail == "invalid_publication_metadata"


def test_no_retry_failed_preserves_only_an_unchanged_failed_result(
    tmp_path: Path,
) -> None:
    # Given
    dependency = "d" * 64
    result = replace(
        _result("a", state=MapBatchState.FAILED),
        dependency_fingerprint=dependency,
    )

    # When
    retained = find_reusable_result(
        _previous(result),
        result.source,
        dependency,
        str(tmp_path),
        retry_failed=False,
    )
    changed = find_reusable_result(
        _previous(result),
        result.source,
        "e" * 64,
        str(tmp_path),
        retry_failed=False,
    )
    retried = find_reusable_result(
        _previous(result),
        result.source,
        dependency,
        str(tmp_path),
        retry_failed=True,
    )

    # Then
    assert retained.result == result
    assert retained.code == "reused_failed_without_retry"
    assert changed.result is None
    assert changed.code == "dependency_changed"
    assert retried.result is None
    assert retried.code == "retry_failed_result"


def test_duplicate_previous_paths_are_never_reused(tmp_path: Path) -> None:
    # Given
    result = _result("a")
    duplicate = replace(
        result,
        source=replace(result.source, sha256="b" * 64),
    )
    previous = PreviousBatchState(
        BatchState(BATCH_SCHEMA_VERSION, (result, duplicate)),
        (),
    )

    # When
    decision = find_reusable_result(
        previous,
        result.source,
        result.dependency_fingerprint,
        str(tmp_path),
        retry_failed=True,
    )

    # Then
    assert decision.result is None
    assert decision.code == "ambiguous_previous_source"


def test_checkpoint_drops_previous_results_for_deleted_sources() -> None:
    # Given
    previous = PreviousBatchState(
        BatchState(BATCH_SCHEMA_VERSION, (_result("a"), _result("deleted"))),
        (),
    )

    # When
    checkpoint = checkpoint_state((_result("a"),), previous, ())

    # Then
    assert [Path(item.source.path).name for item in checkpoint.results] == ["a"]


def _publish_valid_result(
    output_root: Path,
    label: str,
    state: MapBatchState,
    dependency: str,
) -> MapBatchResult:
    fingerprint = _fingerprint(label)
    relative = f"地图/001_{label}_{fingerprint.sha256[:8]}"
    result = replace(
        empty_result(fingerprint, relative),
        **_axis_fields(state),
        dependency_fingerprint=dependency,
    )
    destination = output_root / relative
    destination.mkdir(parents=True)
    return write_empty_publication(destination, result, "1" * 32)


def _previous(result: MapBatchResult) -> PreviousBatchState:
    return PreviousBatchState(BatchState(BATCH_SCHEMA_VERSION, (result,)), ())


def _result(
    label: str,
    *,
    state: MapBatchState = MapBatchState.COMPLETE,
) -> MapBatchResult:
    fingerprint = _fingerprint(label)
    if state is MapBatchState.FAILED:
        return replace(
            empty_result(fingerprint, "unused"),
            output_directory="",
            stage="load/process",
            first_error="broken",
            dependency_fingerprint="",
            **_axis_fields(state),
        )
    return replace(
        empty_result(fingerprint, f"地图/001_{label}_{fingerprint.sha256[:8]}"),
        **_axis_fields(state),
    )


def _axis_fields(state: MapBatchState) -> dict[str, object]:
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
            raise AssertionError(f"unhandled state: {unreachable}")


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


def _fingerprint(label: str) -> SourceFingerprint:
    digest = label * 64
    return SourceFingerprint(f"/maps/{label}", 3, 4, digest)
