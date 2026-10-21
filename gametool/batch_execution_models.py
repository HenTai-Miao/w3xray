"""Typed contracts shared by isolated map execution boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .batch_configuration import BatchOptions
from .batch_models import MapBatchResult, SourceFingerprint
from .load_context import MapLoadContext


class CancellationSignal(Protocol):
    """Minimal cooperative cancellation surface accepted by the runner."""

    def is_set(self) -> bool: ...


class MapWorker(Protocol):
    """Picklable single-map worker callable executed in the child."""

    def __call__(
        self,
        index: int,
        fingerprint: SourceFingerprint,
        options: BatchOptions,
        context: MapLoadContext,
        *,
        dependency_fingerprint: str | None = None,
    ) -> MapBatchResult: ...


@dataclass(frozen=True, slots=True)
class MapExecutionSuccess:
    result: MapBatchResult
    peak_rss_bytes: int = 0


@dataclass(frozen=True, slots=True)
class MapExecutionFailure:
    code: str
    detail: str
    child_alive: bool = False
    peak_rss_bytes: int = 0


@dataclass(frozen=True, slots=True)
class MapExecutionCancelled:
    code: str = "map_cancelled"
    detail: str = ""
    child_alive: bool = False
    peak_rss_bytes: int = 0


type MapExecutionOutcome = (
    MapExecutionSuccess | MapExecutionFailure | MapExecutionCancelled
)


__all__ = (
    "CancellationSignal",
    "MapExecutionCancelled",
    "MapExecutionFailure",
    "MapExecutionOutcome",
    "MapExecutionSuccess",
    "MapWorker",
)
