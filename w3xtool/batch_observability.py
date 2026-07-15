"""Pure conversion from batch outcomes to progress and diagnostic records."""

from __future__ import annotations

from .batch_map_attempt import MapAttempt
from .batch_models import MapBatchResult
from .batch_publication_models import RecoveryDiagnostic
from .batch_resume import ResumeDiagnostic
from .batch_runtime import (
    BatchAction,
    BatchDiagnostic,
    BatchProgress,
    build_batch_progress,
)


def startup_diagnostics(
    resume: tuple[ResumeDiagnostic, ...],
    recovery: tuple[RecoveryDiagnostic, ...],
    total: int,
) -> tuple[BatchDiagnostic, ...]:
    """Convert startup safety evidence into one stable diagnostic sequence."""
    diagnostics = tuple(
        _starting_diagnostic(
            index,
            item.code,
            item.detail,
            item.source_path,
            total,
        )
        for index, item in enumerate(resume, start=1)
    )
    base = len(diagnostics)
    recovered = tuple(
        _starting_diagnostic(
            base + index,
            f"recovery_{item.code}",
            item.detail,
            item.transaction_id,
            total,
        )
        for index, item in enumerate(recovery, start=1)
    )
    return (*diagnostics, *recovered)


def observe_attempt(
    attempt: MapAttempt,
    result: MapBatchResult,
    *,
    sequence: int,
    completed: int,
    total: int,
    source_path: str,
    started_ns: int,
    now_ns: int,
) -> tuple[BatchProgress, BatchDiagnostic]:
    """Build matching callback and JSONL records from the same exact values."""
    progress = build_batch_progress(
        completed=completed,
        total=total,
        source_path=source_path,
        action=attempt.action,
        started_ns=started_ns,
        now_ns=now_ns,
        peak_rss_bytes=result.peak_rss_bytes,
        published_bytes=result.published_bytes,
        diagnostic_code=attempt.code,
    )
    diagnostic = BatchDiagnostic(
        sequence=sequence,
        code=attempt.code,
        detail=attempt.detail,
        source_path=source_path,
        action=attempt.action,
        completed=completed,
        total=total,
        elapsed_ms=progress.elapsed_ms,
        peak_rss_bytes=progress.peak_rss_bytes,
        published_bytes=progress.published_bytes,
    )
    return progress, diagnostic


def _starting_diagnostic(
    sequence: int,
    code: str,
    detail: str,
    source_path: str,
    total: int,
) -> BatchDiagnostic:
    return BatchDiagnostic(
        sequence,
        code,
        detail,
        source_path,
        BatchAction.STARTING,
        0,
        total,
        0,
        0,
        0,
    )


__all__ = ("observe_attempt", "startup_diagnostics")
