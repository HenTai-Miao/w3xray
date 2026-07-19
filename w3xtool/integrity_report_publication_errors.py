"""Failure conversion at the integrity-report publication boundary."""

from __future__ import annotations

from collections.abc import Callable
import errno
from pathlib import Path

from .integrity_report_history import IntegrityHistoryError
from .safe_output_models import SafeWriteResult, SafeWriteStatus


type IntegrityFailureStatus = Callable[[OSError], SafeWriteStatus]


def integrity_publication_failure(
    destination: Path,
    status: SafeWriteStatus,
    reason: str,
) -> SafeWriteResult:
    """Build one zero-byte failure result for a report destination."""
    return SafeWriteResult(status, str(destination), 0, reason)


def integrity_publication_status(
    exc: OSError,
    fallback: IntegrityFailureStatus,
) -> SafeWriteStatus:
    """Map publication identity conflicts to fail-closed unsafe results."""
    if isinstance(exc, IntegrityHistoryError) or exc.errno in {
        errno.EEXIST,
        errno.EBUSY,
    }:
        return SafeWriteStatus.UNSAFE
    return fallback(exc)


__all__ = (
    "IntegrityFailureStatus",
    "integrity_publication_failure",
    "integrity_publication_status",
)
