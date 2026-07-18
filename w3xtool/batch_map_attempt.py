"""One fingerprinted map attempt: reuse, preflight, execute, or cancel."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import struct
from typing import assert_never

from .batch_configuration import BatchOptions
from .batch_dependencies import fingerprint_dependencies
from .batch_execution import (
    CancellationSignal,
    MapExecutionCancelled,
    MapExecutionFailure,
    MapExecutionSuccess,
    MapWorker,
    execute_map_isolated,
)
from .batch_models import MapBatchResult, SourceFingerprint
from .batch_resume import PreviousBatchState, find_reusable_result
from .batch_runtime import (
    BatchAction,
    DiskPreflightInsufficient,
    DiskPreflightReady,
    check_disk_preflight,
    current_peak_rss_bytes,
)
from .batch_status import PublicationResult, derive_batch_axes, derive_legacy_map_state
from .load_context import MapLoadContext


@dataclass(frozen=True, slots=True)
class MapAttempt:
    result: MapBatchResult
    action: BatchAction
    code: str
    detail: str = ""
    stop_batch: bool = False


def attempt_map(
    index: int,
    fingerprint: SourceFingerprint,
    options: BatchOptions,
    context: MapLoadContext,
    previous: PreviousBatchState,
    cache_sha256: str,
    cancellation: CancellationSignal | None,
    worker: MapWorker,
) -> MapAttempt:
    """Resolve one source without crossing an unbounded resource boundary."""
    if cancellation is not None and cancellation.is_set():
        return _cancelled(fingerprint, "cancellation requested")
    try:
        dependency = fingerprint_dependencies(fingerprint, options, cache_sha256)
    except (OSError, ValueError, KeyError, IndexError, struct.error) as exc:
        detail = f"{type(exc).__name__}: {exc}"
        return _failed(fingerprint, "dependency_fingerprint_failed", detail)
    decision = find_reusable_result(
        previous,
        fingerprint,
        dependency,
        options.output_root,
        retry_failed=options.retry_failed,
    )
    if decision.result is not None:
        return MapAttempt(
            decision.result,
            BatchAction.REUSED,
            decision.code,
            decision.detail,
        )
    preflight = check_disk_preflight(
        options.output_root,
        source_size=fingerprint.size,
        minimum_free_bytes=options.minimum_free_bytes,
    )
    match preflight:
        case DiskPreflightInsufficient(
            available_bytes=available,
            required_bytes=required,
        ):
            detail = f"available={available}, required={required}"
            return _failed(fingerprint, "insufficient_disk_space", detail, dependency)
        case DiskPreflightReady():
            pass
        case unreachable:
            assert_never(unreachable)
    if options.map_timeout_seconds is None:
        return _execute_direct(
            index,
            fingerprint,
            options,
            context,
            dependency,
            worker,
        )
    outcome = execute_map_isolated(
        index,
        fingerprint,
        options,
        context,
        worker=worker,
        timeout_seconds=options.map_timeout_seconds,
        max_memory_bytes=options.max_memory_bytes,
        cancellation=cancellation,
    )
    match outcome:
        case MapExecutionSuccess(result=result, peak_rss_bytes=peak):
            published = replace(
                result,
                peak_rss_bytes=max(result.peak_rss_bytes, peak),
            )
            return MapAttempt(published, BatchAction.PROCESSED, "processed")
        case MapExecutionFailure(code=code, detail=detail, peak_rss_bytes=peak):
            return _failed(fingerprint, code, detail, dependency, peak)
        case MapExecutionCancelled(detail=detail, peak_rss_bytes=peak):
            return _cancelled(fingerprint, detail, dependency, peak)
        case unreachable:
            assert_never(unreachable)


def failed_unfingerprinted(path: str, detail: str) -> MapAttempt:
    """Represent a source that changed or became unreadable during hashing."""
    fingerprint = SourceFingerprint(path, 0, 0, "0" * 64)
    return _failed(fingerprint, "source_fingerprint_failed", detail)


def _execute_direct(
    index: int,
    fingerprint: SourceFingerprint,
    options: BatchOptions,
    context: MapLoadContext,
    dependency: str,
    worker: MapWorker,
) -> MapAttempt:
    try:
        result = worker(index, fingerprint, options, context)
    except MemoryError as exc:
        return _failed(
            fingerprint,
            "map_memory_error",
            str(exc),
            dependency,
            current_peak_rss_bytes(),
        )
    except (OSError, ValueError, KeyError, IndexError, struct.error) as exc:
        detail = f"{type(exc).__name__}: {exc}"
        return _failed(fingerprint, "map_processing_error", detail, dependency)
    result = replace(
        result,
        peak_rss_bytes=max(result.peak_rss_bytes, current_peak_rss_bytes()),
    )
    return MapAttempt(result, BatchAction.PROCESSED, "processed")


def _failed(
    fingerprint: SourceFingerprint,
    code: str,
    detail: str,
    dependency: str = "",
    peak_rss_bytes: int = 0,
) -> MapAttempt:
    result = _terminal_result(
        fingerprint,
        "load/process",
        PublicationResult.FAILED,
        code,
        detail,
        dependency,
        peak_rss_bytes,
    )
    return MapAttempt(result, BatchAction.FAILED, code, detail)


def _cancelled(
    fingerprint: SourceFingerprint,
    detail: str,
    dependency: str = "",
    peak_rss_bytes: int = 0,
) -> MapAttempt:
    result = _terminal_result(
        fingerprint,
        "cancelled",
        PublicationResult.CANCELLED,
        "map_cancelled",
        detail,
        dependency,
        peak_rss_bytes,
    )
    return MapAttempt(
        result,
        BatchAction.CANCELLED,
        "map_cancelled",
        detail,
        True,
    )


def _terminal_result(
    fingerprint: SourceFingerprint,
    stage: str,
    publication: PublicationResult,
    code: str,
    detail: str,
    dependency: str,
    peak_rss_bytes: int,
) -> MapBatchResult:
    axes = derive_batch_axes(
        publication,
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
        display_name=Path(fingerprint.path).stem,
        output_directory="",
        stage=stage,
        state=derive_legacy_map_state(axes),
        first_error=f"{code}: {detail}".replace("\n", " "),
        object_count=0,
        description_counts=(),
        named_icon_count=0,
        anonymous_icon_count=0,
        original_written_count=0,
        png_written_count=0,
        icon_failure_count=0,
        restricted_block_count=0,
        elapsed_ms=0,
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
        dependency_fingerprint=dependency,
        peak_rss_bytes=max(0, peak_rss_bytes),
    )


__all__ = ("MapAttempt", "attempt_map", "failed_unfingerprinted")
