"""Resource preflight, deterministic progress, and JSONL diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
from pathlib import Path
import shutil
import sys
from typing import Final


_EXPANSION_FACTOR: Final = 3
_MIN_EXPANSION_BYTES: Final = 64 * 1024 * 1024


class BatchAction(StrEnum):
    STARTING = "starting"
    PROCESSED = "processed"
    REUSED = "reused"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class DiskPreflightReady:
    available_bytes: int
    required_bytes: int


@dataclass(frozen=True, slots=True)
class DiskPreflightInsufficient:
    available_bytes: int
    required_bytes: int


type DiskPreflight = DiskPreflightReady | DiskPreflightInsufficient


@dataclass(frozen=True, slots=True)
class BatchProgress:
    completed: int
    total: int
    source_path: str
    action: BatchAction
    elapsed_ms: int
    eta_seconds: float | None
    peak_rss_bytes: int
    published_bytes: int
    diagnostic_code: str


@dataclass(frozen=True, slots=True)
class BatchDiagnostic:
    sequence: int
    code: str
    detail: str
    source_path: str
    action: BatchAction
    completed: int
    total: int
    elapsed_ms: int
    peak_rss_bytes: int
    published_bytes: int


def check_disk_preflight(
    output_root: str,
    *,
    source_size: int,
    minimum_free_bytes: int,
) -> DiskPreflight:
    """Require a reserve plus a conservative source expansion budget."""
    probe = Path(output_root)
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    available = max(0, shutil.disk_usage(probe).free)
    expansion = max(
        _MIN_EXPANSION_BYTES,
        max(0, source_size) * _EXPANSION_FACTOR,
    )
    required = max(0, minimum_free_bytes) + expansion
    if available < required:
        return DiskPreflightInsufficient(available, required)
    return DiskPreflightReady(available, required)


def build_batch_progress(
    *,
    completed: int,
    total: int,
    source_path: str,
    action: BatchAction,
    started_ns: int,
    now_ns: int,
    peak_rss_bytes: int,
    published_bytes: int,
    diagnostic_code: str,
) -> BatchProgress:
    """Build nonnegative elapsed time and ETA from injected monotonic values."""
    elapsed_ns = max(0, now_ns - started_ns)
    elapsed_ms = elapsed_ns // 1_000_000
    eta = None
    if completed > 0 and total > completed:
        remaining = total - completed
        eta = round((elapsed_ns / 1_000_000_000) * remaining / completed, 3)
    return BatchProgress(
        max(0, completed),
        max(0, total),
        source_path,
        action,
        elapsed_ms,
        eta,
        max(0, peak_rss_bytes),
        max(0, published_bytes),
        diagnostic_code,
    )


def format_batch_diagnostics_jsonl(
    diagnostics: tuple[BatchDiagnostic, ...],
) -> str:
    """Serialize structured diagnostics without truncating their text."""
    return "".join(
        json.dumps(
            {
                "action": item.action.value,
                "code": item.code,
                "completed": item.completed,
                "detail": item.detail,
                "elapsed_ms": item.elapsed_ms,
                "peak_rss_bytes": item.peak_rss_bytes,
                "published_bytes": item.published_bytes,
                "sequence": item.sequence,
                "source_path": item.source_path,
                "total": item.total,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
        for item in diagnostics
    )


def current_peak_rss_bytes() -> int:
    """Return this process peak RSS, or zero when the platform lacks it."""
    try:
        import resource
    except ImportError:
        return 0
    value = max(0, int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss))
    return value if sys.platform == "darwin" else value * 1024


__all__ = (
    "BatchAction",
    "BatchDiagnostic",
    "BatchProgress",
    "DiskPreflight",
    "DiskPreflightInsufficient",
    "DiskPreflightReady",
    "build_batch_progress",
    "check_disk_preflight",
    "current_peak_rss_bytes",
    "format_batch_diagnostics_jsonl",
)
