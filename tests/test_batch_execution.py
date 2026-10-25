"""Spawn-isolated map execution lifecycle contracts."""

from __future__ import annotations

import multiprocessing
import os
from pathlib import Path
import threading
from time import monotonic
import pytest

from gametool.batch_configuration import BatchOptions
from gametool.batch_execution import (
    MapExecutionCancelled,
    MapExecutionFailure,
    MapExecutionSuccess,
    _wait_for_child,
    execute_map_isolated,
)
from gametool.batch_execution_messages import (
    ChildSuccess,
    decode_child_message,
    encode_child_success,
)
from gametool.batch_execution_request import build_execution_request
from gametool.batch_models import MapBatchResult, MapBatchState, SourceFingerprint
from gametool.batch_status import PublicationResult, derive_batch_axes
from gametool.description_cache_models import DescriptionCache, DescriptionCacheEntry
from gametool.load_context import MapLoadContext


@pytest.mark.parametrize("timeout_seconds", [2.0, None])
def test_success_returns_child_result_and_reaps_process(
    tmp_path: Path, timeout_seconds: float | None
) -> None:
    # Given
    before = _active_child_ids()

    # When
    outcome = _execute(tmp_path, _success_worker, timeout_seconds=timeout_seconds)

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


@pytest.mark.parametrize("timeout_seconds", [2.0, None])
def test_cancellation_returns_explicit_cancelled_outcome(
    tmp_path: Path, timeout_seconds: float | None
) -> None:
    # Given
    signal = threading.Event()
    timer = threading.Timer(0.02, signal.set)
    timer.start()

    # When
    try:
        outcome = _execute(
            tmp_path,
            _blocking_worker,
            timeout_seconds=timeout_seconds,
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
    timeout_seconds: float | None,
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
    **_kwargs: object,
) -> MapBatchResult:
    axes = derive_batch_axes(
        PublicationResult.PUBLISHED,
        raw_blocks=0,
        damaged_blocks=0,
        restricted_blocks=0,
        icon_gaps=0,
        current_text_states=(),
        relation_partial_count=0,
        unresolved_endpoint_count=0,
    )
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
        publication_result=axes.publication,
        archive_integrity=axes.archive,
        knowledge_evidence=axes.knowledge,
        knowledge_gap_reasons=axes.knowledge_reasons,
        raw_block_count=0,
        damaged_block_count=0,
        valid_icon_reference_count=0,
        resolved_icon_reference_count=0,
        filtered_icon_field_count=0,
        unresolved_icon_count=0,
        unresolved_icon_reference_count=0,
        anonymous_read_failure_count=0,
        original_write_failure_count=0,
        png_failure_count=0,
        dependency_fingerprint="b" * 64,
        manifest_sha256="c" * 64,
        published_bytes=1,
    )


def _blocking_worker(
    _index: int,
    _fingerprint: SourceFingerprint,
    _options: BatchOptions,
    _context: MapLoadContext,
    **_kwargs: object,
) -> MapBatchResult:
    _ = threading.Event().wait(60)
    raise AssertionError("blocking worker was not terminated")


def _hard_exit_worker(
    _index: int,
    _fingerprint: SourceFingerprint,
    _options: BatchOptions,
    _context: MapLoadContext,
    **_kwargs: object,
) -> MapBatchResult:
    os._exit(7)


def _memory_error_worker(
    _index: int,
    _fingerprint: SourceFingerprint,
    _options: BatchOptions,
    _context: MapLoadContext,
    **_kwargs: object,
) -> MapBatchResult:
    raise MemoryError("test oom")


def _active_child_ids() -> frozenset[int | None]:
    return frozenset(process.pid for process in multiprocessing.active_children())


class _OversizePayloadReceiver:
    """模拟子进程载荷超过 recv_bytes(maxlength) 传输上限的 Windows 管道。"""

    def __init__(self) -> None:
        self.calls = 0

    def poll(self, timeout: float = 0.0) -> bool:
        _ = timeout
        return True

    def recv_bytes(self, maxlength: int | None = None) -> bytes:
        self.calls += 1
        _ = maxlength
        raise OSError("[WinError 233] 管道已结束 — 载荷超过 maxlength 上限")

    def close(self) -> None:
        return None


class _AliveProcess:
    exitcode = None

    def __init__(self) -> None:
        self.terminated = False

    def is_alive(self) -> bool:
        return not self.terminated

    def join(self, timeout: float | None = None) -> None:
        _ = timeout

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.terminated = True

    def close(self) -> None:
        return None


class _ImmediateCancel:
    def is_set(self) -> bool:
        return True


def test_oversize_payload_diagnosed_not_crash() -> None:
    # Given: 子进程回传载荷超过传输上限, recv_bytes 抛 OSError (旧版裸炸 traceback)
    process = _AliveProcess()
    receiver = _OversizePayloadReceiver()

    # When
    outcome = _wait_for_child(process, receiver, monotonic() + 60.0, None)

    # Then: 诊断为具名失败, 不是未捕获异常
    assert isinstance(outcome, MapExecutionFailure)
    assert outcome.code == "child_message_read_failed"
    assert "transport failed" in outcome.detail
    assert receiver.calls >= 1


@pytest.mark.parametrize("cancel", [True, False])
def test_partial_payload_receive_remains_cancellable_and_times_out(
    cancel: bool,
) -> None:
    released = threading.Event()
    signal = threading.Event()

    class ReceivingProcess(_AliveProcess):
        def terminate(self) -> None:
            super().terminate()
            released.set()

    class PartialReceiver:
        expired = False

        def poll(self, timeout: float = 0.0) -> bool:
            return True

        def recv_bytes(self, maxlength: int | None = None) -> bytes:
            if cancel:
                signal.set()
            self.expired = not released.wait(1.5)
            raise EOFError

        def close(self) -> None:
            released.set()

    process = ReceivingProcess()
    receiver = PartialReceiver()
    outcome = _wait_for_child(
        process, receiver, None if cancel else monotonic() + 0.2, signal
    )
    assert not receiver.expired
    assert process.terminated
    if cancel:
        assert isinstance(outcome, MapExecutionCancelled)
    else:
        assert isinstance(outcome, MapExecutionFailure)
        assert outcome.code == "map_timeout"


@pytest.mark.parametrize("failure", [MemoryError, ValueError, OverflowError])
def test_receive_failure_delivers_result_instead_of_waiting_forever(
    failure: type[Exception],
) -> None:
    class FailedReceiver(_OversizePayloadReceiver):
        def recv_bytes(self, maxlength: int | None = None) -> bytes:
            raise failure("fixture receive failure")

    outcome = _wait_for_child(
        _AliveProcess(), FailedReceiver(), monotonic() + 0.5, None
    )
    assert isinstance(outcome, MapExecutionFailure)
    assert outcome.code == (
        "child_message_memory_error"
        if failure is MemoryError
        else "child_message_read_failed"
    )


def test_decode_memory_error_is_diagnosed(monkeypatch: pytest.MonkeyPatch) -> None:
    from gametool import batch_execution

    def exhausted(_payload: bytes) -> None:
        raise MemoryError("fixture decode failure")

    monkeypatch.setattr(batch_execution, "decode_child_message", exhausted)
    result = batch_execution._execution_outcome(b"Sfixture")
    assert isinstance(result, MapExecutionFailure)
    assert result.code == "child_message_memory_error"
