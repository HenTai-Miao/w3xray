"""Spawn-isolated execution with bounded cancellation and process cleanup."""

from __future__ import annotations

import multiprocessing
import struct
from time import monotonic
from typing import Protocol, assert_never

from .batch_configuration import BatchOptions
from .batch_execution_models import (
    CancellationSignal,
    MapExecutionCancelled,
    MapExecutionFailure,
    MapExecutionOutcome,
    MapExecutionSuccess,
    MapWorker,
)
from .batch_execution_messages import (
    ChildFailure,
    ChildSuccess,
    decode_child_message,
    encode_child_failure,
    encode_child_success,
)
from .batch_execution_request import MapExecutionRequest, build_execution_request
from .batch_map_processing import process_one_map
from .batch_models import SourceFingerprint
from .batch_runtime import current_peak_rss_bytes
from .load_context import MapLoadContext


_POLL_SECONDS = 0.025
_JOIN_SECONDS = 0.2
_MAX_MESSAGE_BYTES = 64 * 1024 * 1024


class _ProcessHandle(Protocol):
    @property
    def exitcode(self) -> int | None: ...

    def is_alive(self) -> bool: ...

    def join(self, timeout: float | None = None) -> None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    def close(self) -> None: ...


class _Receiver(Protocol):
    def poll(self, timeout: float = 0.0) -> bool: ...

    def recv_bytes(self, maxlength: int | None = None) -> bytes: ...

    def close(self) -> None: ...


class _Sender(Protocol):
    def send_bytes(self, buffer: bytes) -> None: ...

    def close(self) -> None: ...


def execute_map_isolated(
    index: int,
    fingerprint: SourceFingerprint,
    options: BatchOptions,
    context: MapLoadContext,
    *,
    worker: MapWorker = process_one_map,
    timeout_seconds: float,
    max_memory_bytes: int | None,
    cancellation: CancellationSignal | None,
    dependency_fingerprint: str | None = None,
) -> MapExecutionOutcome:
    """Run one map in a spawn child and reap it on every outcome."""
    request = build_execution_request(
        index,
        fingerprint,
        options,
        context,
        dependency_fingerprint=dependency_fingerprint,
    )
    process_context = multiprocessing.get_context("spawn")
    receiver, sender = process_context.Pipe(duplex=False)
    process = process_context.Process(
        target=_child_entry,
        args=(request, sender, worker, max_memory_bytes),
        daemon=False,
    )
    try:
        process.start()
    except (OSError, TypeError, AttributeError) as exc:
        receiver.close()
        sender.close()
        process.close()
        return MapExecutionFailure("child_start_failed", str(exc))
    sender.close()
    try:
        return _wait_for_child(
            process,
            receiver,
            monotonic() + max(0.0, timeout_seconds),
            cancellation,
        )
    finally:
        _stop_and_reap(process)
        receiver.close()
        process.close()


def _child_entry(
    request: MapExecutionRequest,
    sender: _Sender,
    worker: MapWorker,
    max_memory_bytes: int | None,
) -> None:
    try:
        limit_failure = _apply_memory_limit(max_memory_bytes)
        if limit_failure is not None:
            sender.send_bytes(
                encode_child_failure(limit_failure.code, limit_failure.detail)
            )
            return
        try:
            result = worker(
                request.index,
                request.fingerprint,
                request.options,
                request.context(),
                dependency_fingerprint=request.dependency_fingerprint,
            )
        except MemoryError as exc:
            sender.send_bytes(
                encode_child_failure(
                    "map_memory_error",
                    str(exc),
                    current_peak_rss_bytes(),
                )
            )
        except (OSError, ValueError, KeyError, IndexError, struct.error) as exc:
            sender.send_bytes(
                encode_child_failure(
                    "map_processing_error",
                    f"{type(exc).__name__}: {exc}",
                    current_peak_rss_bytes(),
                )
            )
        else:
            sender.send_bytes(encode_child_success(result, current_peak_rss_bytes()))
    finally:
        sender.close()


def _wait_for_child(
    process: _ProcessHandle,
    receiver: _Receiver,
    deadline: float,
    cancellation: CancellationSignal | None,
) -> MapExecutionOutcome:
    while True:
        if cancellation is not None and cancellation.is_set():
            _stop_and_reap(process)
            return MapExecutionCancelled()
        remaining = deadline - monotonic()
        if remaining <= 0:
            _stop_and_reap(process)
            return MapExecutionFailure("map_timeout", "map execution timed out")
        if _receiver_has_payload(receiver, min(_POLL_SECONDS, remaining)):
            try:
                payload = receiver.recv_bytes(_MAX_MESSAGE_BYTES)
            except EOFError:
                payload = b""
            if payload:
                return _execution_outcome(payload)
        if not process.is_alive():
            process.join()
            if _receiver_has_payload(receiver, _POLL_SECONDS):
                try:
                    payload = receiver.recv_bytes(_MAX_MESSAGE_BYTES)
                except EOFError:
                    payload = b""
                if payload:
                    return _execution_outcome(payload)
            return MapExecutionFailure(
                "child_process_exit",
                f"child exited with code {process.exitcode}",
            )


def _receiver_has_payload(receiver: _Receiver, timeout: float) -> bool:
    """Treat Windows' ended named pipe as an empty child response."""
    try:
        return receiver.poll(timeout)
    except BrokenPipeError, EOFError:
        return False


def _stop_and_reap(process: _ProcessHandle) -> None:
    if process.is_alive():
        process.terminate()
    process.join(_JOIN_SECONDS)
    if process.is_alive():
        process.kill()
        process.join(_JOIN_SECONDS)


def _apply_memory_limit(max_memory_bytes: int | None) -> MapExecutionFailure | None:
    if max_memory_bytes is None:
        return None
    try:
        import resource
    except ImportError:
        return None
    if not hasattr(resource, "RLIMIT_AS"):
        return None
    try:
        resource.setrlimit(resource.RLIMIT_AS, (max_memory_bytes, max_memory_bytes))
    except (OSError, ValueError) as exc:
        return MapExecutionFailure("memory_limit_setup_failed", str(exc))
    return None


def _execution_outcome(payload: bytes) -> MapExecutionOutcome:
    message = decode_child_message(payload)
    match message:
        case ChildSuccess(result=result, peak_rss_bytes=peak):
            return MapExecutionSuccess(result, peak)
        case ChildFailure(code=code, detail=detail, peak_rss_bytes=peak):
            return MapExecutionFailure(code, detail, peak_rss_bytes=peak)
        case unreachable:
            assert_never(unreachable)


__all__ = (
    "CancellationSignal",
    "MapExecutionCancelled",
    "MapExecutionFailure",
    "MapExecutionOutcome",
    "MapExecutionSuccess",
    "MapWorker",
    "execute_map_isolated",
)
