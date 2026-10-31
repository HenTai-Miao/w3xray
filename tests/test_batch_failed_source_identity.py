"""Unreadable inputs retain distinct failure evidence through batch checkpoints."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

import gametool.batch_runner as batch_runner
from gametool.batch_configuration import BatchOptions
from gametool.batch_map_attempt import failed_unfingerprinted
from gametool.batch_models import (
    BATCH_SCHEMA_VERSION,
    BatchState,
    BatchStateFormatError,
)
from gametool.batch_reports import format_batch_state_json, parse_batch_state_json
from gametool.batch_resume import (
    PreviousBatchState,
    checkpoint_state,
    load_previous_state,
)
from gametool.batch_status import PublicationResult
from gametool.load_context import MapLoadContext
from tests.batch_publication_fixture import empty_result


def test_distinct_unreadable_sources_round_trip_without_content_deduplication() -> None:
    first = failed_unfingerprinted("/maps/a.w3x", "permission denied").result
    second = failed_unfingerprinted("/maps/b.w3x", "source changed").result
    state = BatchState(BATCH_SCHEMA_VERSION, (first, second))

    assert parse_batch_state_json(format_batch_state_json(state)) == state


def test_unreadable_source_path_duplicates_are_still_rejected() -> None:
    result = failed_unfingerprinted("/maps/a.w3x", "permission denied").result
    duplicate = replace(result, source=replace(result.source, path="/MAPS/A.W3X"))

    with pytest.raises(BatchStateFormatError, match="duplicate source"):
        parse_batch_state_json(
            format_batch_state_json(
                BatchState(BATCH_SCHEMA_VERSION, (result, duplicate))
            )
        )


def test_confirmed_content_duplicates_are_still_rejected() -> None:
    result = failed_unfingerprinted("/maps/a.w3x", "permission denied").result
    result = replace(
        result, source=replace(result.source, size=3, mtime_ns=4, sha256="a" * 64)
    )
    duplicate = replace(result, source=replace(result.source, path="/maps/b.w3x"))

    with pytest.raises(BatchStateFormatError, match="duplicate source"):
        parse_batch_state_json(
            format_batch_state_json(
                BatchState(BATCH_SCHEMA_VERSION, (result, duplicate))
            )
        )


def test_unreadable_source_cannot_claim_a_published_content_identity() -> None:
    source = failed_unfingerprinted("/maps/a.w3x", "permission denied").result.source
    result = replace(
        empty_result(source, "地图/001_map_00000000"), manifest_sha256="a" * 64
    )

    with pytest.raises(BatchStateFormatError, match="unreadable source"):
        parse_batch_state_json(
            format_batch_state_json(BatchState(BATCH_SCHEMA_VERSION, (result,)))
        )


def test_checkpoint_preserves_unvisited_unreadable_sources() -> None:
    first = failed_unfingerprinted("/maps/a.w3x", "permission denied").result
    second = failed_unfingerprinted("/maps/b.w3x", "source changed").result
    previous = PreviousBatchState(BatchState(BATCH_SCHEMA_VERSION, (first, second)), ())

    state = checkpoint_state((first,), previous, (second.source.path,))

    assert state.results == (first, second)


def test_batch_publishes_all_unreadable_sources_and_can_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_root = tmp_path / "Maps"
    source_root.mkdir()
    paths = tuple(source_root / name for name in ("a.w3x", "b.w3x", "c.w3x"))
    for path in paths:
        path.write_bytes(path.name.encode("ascii"))

    def unreadable(path: str) -> None:
        raise PermissionError(f"cannot read {Path(path).name}")

    monkeypatch.setattr(batch_runner, "fingerprint_source", unreadable)
    monkeypatch.setattr(
        batch_runner, "build_map_load_context", lambda **_kwargs: MapLoadContext()
    )
    options = BatchOptions(str(source_root), str(tmp_path / "output"))

    first = batch_runner.run_batch(options)
    resumed = batch_runner.run_batch(options)
    restored = load_previous_state(options.output_root)

    assert len(first.results) == len(paths)
    assert {item.source.path for item in first.results} == {str(path) for path in paths}
    assert all(
        item.publication_result is PublicationResult.FAILED for item in first.results
    )
    assert all(
        "source_fingerprint_failed" in item.first_error for item in first.results
    )
    assert restored.diagnostics == ()
    assert restored.state == resumed == first
