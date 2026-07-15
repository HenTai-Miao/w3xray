"""Runner integration for disk preflight, cancellation, and progress."""

from __future__ import annotations

import json
from pathlib import Path
import threading

import pytest

from tests.batch_publication_fixture import publish_empty_result
import w3xtool.batch_output_lock as batch_output_lock
import w3xtool.batch_runner as batch_runner
from w3xtool.batch_configuration import BatchOutputError
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


def test_concurrent_batches_cannot_share_one_output_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: one batch owns the output root while its map processor is active.
    source_root = _source_root(tmp_path)
    output = tmp_path / "output"
    options = BatchOptions(str(source_root), str(output))
    entered = threading.Event()
    release = threading.Event()
    calls_lock = threading.Lock()
    calls = 0
    failures: list[BaseException] = []
    _patch_context(monkeypatch)

    def process(
        index: int,
        fingerprint: SourceFingerprint,
        current: BatchOptions,
        _context: MapLoadContext,
    ) -> MapBatchResult:
        nonlocal calls
        with calls_lock:
            calls += 1
            call_number = calls
        if call_number == 1:
            entered.set()
            if not release.wait(timeout=5):
                raise AssertionError("test did not release the first batch")
        return publish_empty_result(index, fingerprint, current.output_root)

    def first_run() -> None:
        try:
            _ = run_batch(options)
        except BaseException as exc:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK - thread outcome is asserted below.
            failures.append(exc)

    monkeypatch.setattr(batch_runner, "process_one_map", process)
    worker = threading.Thread(target=first_run, name="batch-output-lock-test")
    worker.start()
    assert entered.wait(timeout=5)

    # When/Then: a second writer fails before processing or publishing anything.
    try:
        with pytest.raises(BatchOutputError, match="in use"):
            _ = run_batch(options)
    finally:
        release.set()
        worker.join(timeout=5)
    assert not worker.is_alive()
    assert failures == []
    assert calls == 1


def test_output_lock_closes_descriptors_when_unlock_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: unlocking fails after one output-root lease was acquired.
    descriptors: tuple[int, int] | None = None
    closed: list[int] = []
    real_close = batch_output_lock.os.close

    def fail_unlock(_descriptor: int) -> None:
        raise OSError("unlock failed")

    def record_close(descriptor: int) -> None:
        closed.append(descriptor)
        real_close(descriptor)

    monkeypatch.setattr(batch_output_lock, "_unlock_descriptor", fail_unlock)
    monkeypatch.setattr(batch_output_lock.os, "close", record_close)

    # When: the lease exits through the cleanup failure.
    with pytest.raises(OSError, match="unlock failed"):
        with batch_output_lock.hold_batch_output_lock(tmp_path / "output") as lease:
            descriptors = (lease.lock_descriptor, lease.root_descriptor)
    assert descriptors is not None
    observed = set(closed)
    for descriptor in descriptors:
        if descriptor not in observed:
            real_close(descriptor)

    # Then: both acquired lease descriptors were still closed.
    assert set(descriptors).issubset(observed)


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
