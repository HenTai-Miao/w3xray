"""Spawn-isolated map execution lifecycle contracts."""

from __future__ import annotations

import multiprocessing
import os
from pathlib import Path
import threading

from w3xtool.batch_configuration import BatchOptions
from w3xtool.batch_execution import (
    MapExecutionCancelled,
    MapExecutionFailure,
    MapExecutionSuccess,
    execute_map_isolated,
)
from w3xtool.batch_execution_messages import (
    ChildSuccess,
    decode_child_message,
    encode_child_success,
)
from w3xtool.batch_execution_request import build_execution_request
from w3xtool.batch_models import MapBatchResult, MapBatchState, SourceFingerprint
from w3xtool.description_cache_models import DescriptionCache, DescriptionCacheEntry
from w3xtool.load_context import MapLoadContext


def test_success_returns_child_result_and_reaps_process(tmp_path: Path) -> None:
    # Given
    before = _active_child_ids()

    # When
    outcome = _execute(tmp_path, _success_worker, timeout_seconds=2.0)

    # Then
    assert isinstance(outcome, MapExecutionSuccess)
    assert outcome.result.display_name == "sample"
    assert _active_child_ids() == before


def test_timeout_terminates_and_reaps_child(tmp_path: Path) -> None:
    # Given
    before = _active_child_ids()

    # When
    outcome = _execute(tmp_path, _blocking_worker, timeout_seconds=0.05)

    # Then
    assert isinstance(outcome, MapExecutionFailure)
    assert outcome.code == "map_timeout"
    assert outcome.child_alive is False
    assert _active_child_ids() == before


def test_cancellation_returns_explicit_cancelled_outcome(tmp_path: Path) -> None:
    # Given
    signal = threading.Event()
    timer = threading.Timer(0.02, signal.set)
    timer.start()

    # When
    try:
        outcome = _execute(
            tmp_path,
            _blocking_worker,
            timeout_seconds=2.0,
            cancellation=signal,
        )
    finally:
        timer.cancel()

    # Then
    assert isinstance(outcome, MapExecutionCancelled)
    assert outcome.code == "map_cancelled"
    assert outcome.child_alive is False


def test_hard_child_exit_is_reported_without_leaking_process(tmp_path: Path) -> None:
    # When
    outcome = _execute(tmp_path, _hard_exit_worker, timeout_seconds=2.0)

    # Then
    assert isinstance(outcome, MapExecutionFailure)
    assert outcome.code == "child_process_exit"
    assert "7" in outcome.detail
    assert outcome.child_alive is False


def test_child_memory_error_is_typed_and_reaped(tmp_path: Path) -> None:
    # When
    outcome = _execute(tmp_path, _memory_error_worker, timeout_seconds=2.0)

    # Then
    assert isinstance(outcome, MapExecutionFailure)
    assert outcome.code == "map_memory_error"
    assert outcome.child_alive is False


def test_child_message_round_trip_preserves_peak_rss(tmp_path: Path) -> None:
    # Given
    fingerprint = SourceFingerprint(str(tmp_path / "sample.w3x"), 3, 4, "a" * 64)
    result = _success_worker(
        1,
        fingerprint,
        BatchOptions(str(tmp_path), str(tmp_path / "output")),
        MapLoadContext(),
    )

    # When
    message = decode_child_message(encode_child_success(result, 123))

    # Then
    assert isinstance(message, ChildSuccess)
    assert message.peak_rss_bytes == 123


def test_execution_request_carries_cache_entries_without_trusted_root(
    tmp_path: Path,
) -> None:
    # Given: the parent has already verified one explicit cache generation.
    fingerprint = SourceFingerprint(str(tmp_path / "sample.w3x"), 3, 4, "a" * 64)
    options = BatchOptions(
        str(tmp_path / "maps"),
        str(tmp_path / "output"),
        description_cache_path=str(tmp_path / "trusted"),
    )
    entry = DescriptionCacheEntry(
        "物品",
        "ratf",
        "扩展提示",
        None,
        "缓存全文",
        "缓存全文",
        "b" * 64,
        "c" * 64,
        "owned.tsv",
    )
    context = MapLoadContext(description_cache=DescriptionCache.build((entry,)))

    # When
    request = build_execution_request(1, fingerprint, options, context)

    # Then: children receive immutable values, never a path they could re-trust.
    assert request.options.description_cache_path is None
    assert request.context().description_cache.entries == (entry,)


def _execute(
    tmp_path: Path,
    worker,
    *,
    timeout_seconds: float,
    cancellation: threading.Event | None = None,
):
    fingerprint = SourceFingerprint(str(tmp_path / "sample.w3x"), 3, 4, "a" * 64)
    return execute_map_isolated(
        1,
        fingerprint,
        BatchOptions(str(tmp_path / "maps"), str(tmp_path / "output")),
        MapLoadContext(),
        worker=worker,
        timeout_seconds=timeout_seconds,
        max_memory_bytes=None,
        cancellation=cancellation,
    )


def _success_worker(
    _index: int,
    fingerprint: SourceFingerprint,
    _options: BatchOptions,
    _context: MapLoadContext,
) -> MapBatchResult:
    return MapBatchResult(
        source=fingerprint,
        display_name="sample",
        output_directory="地图/001_sample_aaaaaaaa",
        stage="published",
        state=MapBatchState.COMPLETE,
        first_error="",
        object_count=0,
        description_counts=(),
        named_icon_count=0,
        anonymous_icon_count=0,
        original_written_count=0,
        png_written_count=0,
        icon_failure_count=0,
        restricted_block_count=0,
        elapsed_ms=1,
        dependency_fingerprint="b" * 64,
        manifest_sha256="c" * 64,
        published_bytes=1,
    )


def _blocking_worker(
    _index: int,
    _fingerprint: SourceFingerprint,
    _options: BatchOptions,
    _context: MapLoadContext,
) -> MapBatchResult:
    _ = threading.Event().wait(60)
    raise AssertionError("blocking worker was not terminated")


def _hard_exit_worker(
    _index: int,
    _fingerprint: SourceFingerprint,
    _options: BatchOptions,
    _context: MapLoadContext,
) -> MapBatchResult:
    os._exit(7)


def _memory_error_worker(
    _index: int,
    _fingerprint: SourceFingerprint,
    _options: BatchOptions,
    _context: MapLoadContext,
) -> MapBatchResult:
    raise MemoryError("test oom")


def _active_child_ids() -> frozenset[int | None]:
    return frozenset(process.pid for process in multiprocessing.active_children())
