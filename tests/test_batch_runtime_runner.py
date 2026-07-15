"""Runner integration for disk preflight, cancellation, and progress."""

from __future__ import annotations

import json
from pathlib import Path
import threading

import pytest

from tests.batch_publication_fixture import publish_empty_result
import w3xtool.batch_runner as batch_runner
from w3xtool.batch_global_publication import load_current_generation
from w3xtool.batch_models import MapBatchResult, MapBatchState, SourceFingerprint
from w3xtool.batch_runner import BatchOptions, run_batch
from w3xtool.batch_runtime import BatchAction, BatchProgress
from w3xtool.load_context import MapLoadContext


def test_disk_preflight_failure_never_calls_map_processor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    source_root = _source_root(tmp_path)
    calls = 0
    _patch_context(monkeypatch)

    def process(
        _index: int,
        _fingerprint: SourceFingerprint,
        _options: BatchOptions,
        _context: MapLoadContext,
    ) -> MapBatchResult:
        nonlocal calls
        calls += 1
        raise AssertionError("disk preflight must run first")

    monkeypatch.setattr(batch_runner, "process_one_map", process)

    # When
    state = run_batch(
        BatchOptions(
            str(source_root),
            str(tmp_path / "output"),
            minimum_free_bytes=10**30,
        )
    )

    # Then
    assert calls == 0
    assert state.results[0].state is MapBatchState.FAILED
    assert "insufficient_disk_space" in state.results[0].first_error


def test_pre_cancelled_batch_publishes_cancelled_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    source_root = _source_root(tmp_path)
    cancellation = threading.Event()
    cancellation.set()
    progress: list[BatchProgress] = []
    _patch_context(monkeypatch)

    def unexpected(*_args) -> MapBatchResult:
        raise AssertionError("cancelled batch must not process a map")

    monkeypatch.setattr(batch_runner, "process_one_map", unexpected)

    # When
    state = run_batch(
        BatchOptions(str(source_root), str(tmp_path / "output")),
        cancellation=cancellation,
        on_progress=progress.append,
    )

    # Then
    assert state.results[0].state is MapBatchState.CANCELLED
    assert progress[-1].action is BatchAction.CANCELLED
    assert progress[-1].completed == 1
    loaded = load_current_generation(tmp_path / "output")
    assert loaded is not None
    assert loaded.state == state


def test_processed_progress_matches_structured_global_diagnostic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    source_root = _source_root(tmp_path)
    progress: list[BatchProgress] = []
    _patch_context(monkeypatch)

    def process(
        index: int,
        fingerprint: SourceFingerprint,
        options: BatchOptions,
        _context: MapLoadContext,
    ) -> MapBatchResult:
        return publish_empty_result(index, fingerprint, options.output_root)

    monkeypatch.setattr(batch_runner, "process_one_map", process)

    # When
    state = run_batch(
        BatchOptions(str(source_root), str(tmp_path / "output")),
        on_progress=progress.append,
    )

    # Then
    assert [item.action for item in progress] == [
        BatchAction.STARTING,
        BatchAction.PROCESSED,
    ]
    completed = progress[-1]
    assert (completed.completed, completed.total) == (1, 1)
    assert completed.elapsed_ms >= 0
    generation = load_current_generation(tmp_path / "output")
    assert generation is not None
    diagnostic = json.loads(generation.diagnostics_text.splitlines()[-1])
    assert diagnostic["action"] == "processed"
    assert diagnostic["completed"] == 1
    assert diagnostic["total"] == 1
    assert diagnostic["published_bytes"] == state.results[0].published_bytes


def _source_root(tmp_path: Path) -> Path:
    root = tmp_path / "Maps"
    root.mkdir()
    (root / "sample.w3x").write_bytes(b"map")
    return root


def _patch_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        batch_runner,
        "build_map_load_context",
        lambda **_kwargs: MapLoadContext(),
    )
