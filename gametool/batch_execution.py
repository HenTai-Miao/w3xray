"""Spawn-isolated execution with bounded cancellation and process cleanup."""

from __future__ import annotations

import multiprocessing
from dataclasses import replace
from queue import Empty, Queue
import struct
from threading import Thread
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
from .batch_runtime import maximum_peak_rss_bytes
from .load_context import MapLoadContext
from .windows_worker_memory import (
    WorkerMemoryLimit,
    apply_worker_memory_limit,
    read_peak_rss,
)


_POLL_SECONDS = 0.025
_JOIN_SECONDS = 0.2
_MAX_MESSAGE_BYTES: int | None = None


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
    timeout_seconds: float | None,
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
            None
            if timeout_seconds is None
            else monotonic() + max(0.0, timeout_seconds),
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
        memory_limit = _apply_memory_limit(max_memory_bytes)
        if isinstance(memory_limit, MapExecutionFailure):
            peak = read_peak_rss()
            sender.send_bytes(
                encode_child_failure(
                    memory_limit.code,
                    memory_limit.detail,
                    peak.peak_rss_bytes,
                    peak.diagnostics,
                )
            )
            return
        result = None
        failure: MapExecutionFailure | None = None
        try:
            result = worker(
                request.index,
                request.fingerprint,
                request.options,
                request.context(),
                dependency_fingerprint=request.dependency_fingerprint,
            )
        except MemoryError as exc:
            failure = MapExecutionFailure(
                "map_memory_error",
                f"{str(exc) or 'memory allocation failed'}; "
                f"configured worker committed-byte budget={max_memory_bytes}"
                if max_memory_bytes is not None
                else str(exc),
            )
        except (OSError, ValueError, KeyError, IndexError, struct.error) as exc:
            failure = MapExecutionFailure(
                "map_processing_error", f"{type(exc).__name__}: {exc}"
            )
        finally:
            cleanup_diagnostics = _close_memory_limit(memory_limit)
        peak = read_peak_rss()
        diagnostics = (*cleanup_diagnostics, *peak.diagnostics)
        if failure is not None:
            sender.send_bytes(
                encode_child_failure(
                    failure.code, failure.detail, peak.peak_rss_bytes, diagnostics
                )
            )
        else:
            assert result is not None
            result = replace(
                result,
                peak_rss_bytes=maximum_peak_rss_bytes(
                    result.peak_rss_bytes, peak.peak_rss_bytes
                ),
                resource_diagnostics=(*result.resource_diagnostics, *diagnostics),
            )
            sender.send_bytes(encode_child_success(result, peak.peak_rss_bytes))
    finally:
        sender.close()


def _wait_for_child(
    process: _ProcessHandle,
    receiver: _Receiver,
    deadline: float | None,
    cancellation: CancellationSignal | None,
) -> MapExecutionOutcome:
    received: Queue[bytes | MapExecutionFailure] = Queue(maxsize=1)
    reader: Thread | None = None

    def read_payload() -> None:
        received.put(_recv_child_payload(receiver, deadline))

    try:
        while True:
            if cancellation is not None and cancellation.is_set():
                _stop_and_reap(process)
                return MapExecutionCancelled()
            remaining = None if deadline is None else deadline - monotonic()
            if remaining is not None and remaining <= 0:
                _stop_and_reap(process)
                return MapExecutionFailure("map_timeout", "map execution timed out")
            wait_seconds = (
                _POLL_SECONDS if remaining is None else min(_POLL_SECONDS, remaining)
            )
            if reader is not None:
                try:
                    outcome = received.get(timeout=wait_seconds)
                except Empty:
                    continue
                if isinstance(outcome, MapExecutionFailure):
                    return outcome
                if outcome:
                    return _execution_outcome(outcome)
                process.join(_JOIN_SECONDS)
                return MapExecutionFailure(
                    "child_process_exit", f"child exited with code {process.exitcode}"
                )
            has_payload = _receiver_has_payload(receiver, wait_seconds)
            if not has_payload and not process.is_alive():
                process.join()
                has_payload = _receiver_has_payload(receiver, _POLL_SECONDS)
                if not has_payload:
                    return MapExecutionFailure(
                        "child_process_exit",
                        f"child exited with code {process.exitcode}",
                    )
            if has_payload:
                reader = Thread(
                    target=read_payload, name="gamexray-batch-receive", daemon=True
                )
                reader.start()
                continue
    finally:
        if reader is not None:
            reader.join(_JOIN_SECONDS)


def _recv_child_payload(
    receiver: _Receiver, deadline: float | None
) -> bytes | MapExecutionFailure:
    """Read a full frame; report EOF, transport errors, and explicit budgets."""
    try:
        return receiver.recv_bytes(_MAX_MESSAGE_BYTES)
    except MemoryError:
        return MapExecutionFailure(
            "child_message_memory_error",
            "insufficient memory while receiving child result",
        )
    except (ValueError, OverflowError) as exc:
        return MapExecutionFailure(
            "child_message_read_failed", f"child payload transport failed: {exc}"
        )
    except EOFError:
        return b""
    except OSError as exc:
        remaining = None if deadline is None else deadline - monotonic()
        if remaining is None or remaining > _POLL_SECONDS:
            return MapExecutionFailure(
                "child_message_read_failed"
                if _MAX_MESSAGE_BYTES is None
                else "child_message_too_large",
                f"child payload transport failed: {exc}"
                if _MAX_MESSAGE_BYTES is None
                else f"child payload exceeded {_MAX_MESSAGE_BYTES // 1048576}MB transport cap: {exc}",
            )
        return b""


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


def _apply_memory_limit(
    max_memory_bytes: int | None,
) -> WorkerMemoryLimit | MapExecutionFailure | None:
    try:
        return apply_worker_memory_limit(max_memory_bytes)
    except (OSError, ValueError, AttributeError, MemoryError) as exc:
        return MapExecutionFailure(
            "memory_limit_setup_failed", f"{type(exc).__name__}: {exc}"
        )


def _close_memory_limit(memory_limit: WorkerMemoryLimit | None) -> tuple[str, ...]:
    if memory_limit is None:
        return ()
    try:
        memory_limit.close()
    except OSError as exc:
        return (f"worker_memory_job_cleanup_failed: {exc}",)
    return ()


def _execution_outcome(payload: bytes) -> MapExecutionOutcome:
    try:
        message = decode_child_message(payload)
    except MemoryError:
        return MapExecutionFailure(
            "child_message_memory_error",
            "insufficient memory while decoding child result",
        )
    match message:
        case ChildSuccess(result=result, peak_rss_bytes=peak):
            return MapExecutionSuccess(result, peak)
        case ChildFailure(
            code=code,
            detail=detail,
            peak_rss_bytes=peak,
            resource_diagnostics=diagnostics,
        ):
            return MapExecutionFailure(
                code,
                detail,
                peak_rss_bytes=peak,
                resource_diagnostics=diagnostics,
            )
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
