"""Runner integration for authoritative resume and lossless checkpoints."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from tests.batch_publication_fixture import empty_result, write_empty_publication
import w3xtool.batch_checkpoint_publication as checkpoint_publication
import w3xtool.batch_map_attempt as batch_map_attempt
import w3xtool.batch_runner as batch_runner
from w3xtool.batch_global_publication import load_current_batch_state
from w3xtool.batch_models import (
    BATCH_SCHEMA_VERSION,
    BatchState,
    MapBatchResult,
    MapBatchState,
    SourceFingerprint,
)
from w3xtool.batch_output_lock import BatchOutputLease
from w3xtool.batch_resume import PreviousBatchState
from w3xtool.batch_runner import BatchOptions, BatchOutputError, run_batch
from w3xtool.batch_status import PublicationResult, derive_batch_axes
from w3xtool.load_context import MapLoadContext


def test_runner_reuses_manifest_verified_partial_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    source_root = tmp_path / "Maps"
    source_root.mkdir()
    (source_root / "sample.w3x").write_bytes(b"map")
    dependency = "d" * 64
    calls = 0
    _patch_context(monkeypatch)
    monkeypatch.setattr(
        batch_map_attempt,
        "fingerprint_dependencies",
        lambda *_args: dependency,
    )

    def process(
        index: int,
        fingerprint: SourceFingerprint,
        options: BatchOptions,
        _context: MapLoadContext,
    ) -> MapBatchResult:
        nonlocal calls
        calls += 1
        return _publish_result(
            index,
            fingerprint,
            options.output_root,
            MapBatchState.PARTIAL,
            dependency,
        )

    monkeypatch.setattr(batch_runner, "process_one_map", process)
    options = BatchOptions(str(source_root), str(tmp_path / "output"))
    first = run_batch(options)

    # When
    second = run_batch(options)

    # Then
    assert second == first
    assert second.results[0].state is MapBatchState.PARTIAL
    assert calls == 1
    assert load_current_batch_state(options.output_root) == second


def test_interrupted_checkpoint_keeps_unvisited_previous_tail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    source_root = tmp_path / "Maps"
    source_root.mkdir()
    for name in ("a.w3x", "b.w3x"):
        (source_root / name).write_bytes(name.encode())
    fingerprints = tuple(
        batch_runner.fingerprint_source(str(source_root / name))
        for name in ("a.w3x", "b.w3x")
    )
    previous_results = tuple(
        replace(
            empty_result(source, f"地图/00{index}_{source.sha256[:8]}"),
            dependency_fingerprint="e" * 64,
            manifest_sha256="f" * 64,
            published_bytes=1,
        )
        for index, source in enumerate(fingerprints, start=1)
    )
    previous = PreviousBatchState(
        BatchState(BATCH_SCHEMA_VERSION, previous_results),
        (),
    )
    observed: list[BatchState] = []
    _patch_context(monkeypatch)
    monkeypatch.setattr(
        batch_runner,
        "load_previous_state",
        lambda _root: previous,
        raising=False,
    )
    monkeypatch.setattr(
        batch_map_attempt,
        "fingerprint_dependencies",
        lambda *_args: "d" * 64,
    )
    monkeypatch.setattr(
        batch_runner,
        "process_one_map",
        lambda _index, source, _options, _context: _failed_result(source),
    )

    def stop_after_checkpoint(
        _root: str,
        state: BatchState,
        _cache_text: str,
        _diagnostics_text: str,
        _lease: BatchOutputLease,
    ) -> None:
        observed.append(state)
        raise KeyboardInterrupt

    monkeypatch.setattr(
        batch_runner,
        "publish_batch_checkpoint",
        stop_after_checkpoint,
        raising=False,
    )

    # When / Then
    with pytest.raises(KeyboardInterrupt):
        run_batch(BatchOptions(str(source_root), str(tmp_path / "output")))
    assert [Path(item.source.path).name for item in observed[0].results] == [
        "a.w3x",
        "b.w3x",
    ]
    assert observed[0].results[0].state is MapBatchState.FAILED
    assert observed[0].results[1] == previous_results[1]


def test_runner_recovers_before_loading_authoritative_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    source_root = tmp_path / "Maps"
    source_root.mkdir()
    events: list[str] = []
    _patch_context(monkeypatch)
    monkeypatch.setattr(
        batch_runner,
        "recover_map_publications",
        lambda _root: events.append("recover") or (),
    )
    monkeypatch.setattr(
        batch_runner,
        "load_previous_state",
        lambda _root: events.append("previous") or PreviousBatchState(None, ()),
        raising=False,
    )

    # When
    _ = run_batch(BatchOptions(str(source_root), str(tmp_path / "output")))

    # Then
    assert events[:2] == ["recover", "previous"]


def test_global_checkpoint_failure_is_a_batch_output_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    source_root = tmp_path / "Maps"
    source_root.mkdir()
    _patch_context(monkeypatch)

    def fail_checkpoint(*_args) -> None:
        raise OSError("disk unavailable")

    monkeypatch.setattr(
        checkpoint_publication,
        "publish_global_generation",
        fail_checkpoint,
    )

    # When / Then
    with pytest.raises(BatchOutputError, match="disk unavailable"):
        run_batch(BatchOptions(str(source_root), str(tmp_path / "output")))


def _patch_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        batch_runner,
        "build_map_load_context",
        lambda **_kwargs: MapLoadContext(),
    )


def _publish_result(
    index: int,
    fingerprint: SourceFingerprint,
    output_root: str,
    state: MapBatchState,
    dependency: str,
) -> MapBatchResult:
    relative = f"地图/{index:03d}_{fingerprint.sha256[:8]}"
    axes = derive_batch_axes(
        PublicationResult.PUBLISHED,
        raw_blocks=1 if state is MapBatchState.PARTIAL else 0,
        damaged_blocks=0,
        restricted_blocks=1 if state is MapBatchState.RESTRICTED else 0,
        icon_gaps=0,
        current_text_states=(),
        relation_partial_count=0,
        unresolved_endpoint_count=0,
    )
    result = replace(
        empty_result(fingerprint, relative),
        state=state,
        publication_result=axes.publication,
        archive_integrity=axes.archive,
        knowledge_evidence=axes.knowledge,
        knowledge_gap_reasons=axes.knowledge_reasons,
        raw_block_count=1 if state is MapBatchState.PARTIAL else 0,
        restricted_block_count=1 if state is MapBatchState.RESTRICTED else 0,
        dependency_fingerprint=dependency,
    )
    destination = Path(output_root, relative)
    destination.mkdir(parents=True, exist_ok=True)
    return write_empty_publication(destination, result, f"{index:032x}")


def _failed_result(source: SourceFingerprint) -> MapBatchResult:
    return replace(
        empty_result(source, "unused"),
        output_directory="",
        stage="load/process",
        state=MapBatchState.FAILED,
        first_error="broken",
        dependency_fingerprint="",
    )
