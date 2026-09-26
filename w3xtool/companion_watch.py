"""Pure companion-watch decisions and the off-Tk Warcraft watch loop."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum, unique
import os
from pathlib import Path
import threading
from typing import Final, Protocol, assert_never

from .current_map_models import CurrentMapResolution, ResolutionStatus
from .current_map_process import ProcessProbeReport
from .current_map_snapshot import CurrentMapSnapshot


_PROBE_UNAVAILABLE_NOTE: Final = "无法探测魔兽进程，联动暂停重试 …"
_LOCATE_FAILED_NOTE: Final = "联动定位当前地图失败，稍后重试 …"
_SNAPSHOT_FAILED_NOTE: Final = "联动创建当前地图快照失败，稍后重试 …"
_RUNNING_NO_HINTS_NOTE: Final = "已检测到魔兽运行中，暂未发现当前地图线索 …"
_PRESENTABLE_STATUSES: Final = frozenset(
    {ResolutionStatus.SUGGESTED, ResolutionStatus.AMBIGUOUS}
)


type MapLocator = Callable[[tuple[Path, ...], ProcessProbeReport], CurrentMapResolution]
type SnapshotFactory = Callable[[Path], CurrentMapSnapshot]


@unique
class CompanionEvent(StrEnum):
    """Edge observed between two usable game-process probes."""

    GAME_STARTED = "game_started"
    GAME_EXITED = "game_exited"


class CompanionHooks(Protocol):
    """Watch-loop events; implementations must marshal onto the Tk thread."""

    def on_game_started(self) -> None: ...

    def on_game_exited(self) -> None: ...

    def on_map_ready(self, snapshot: CurrentMapSnapshot) -> None: ...

    def on_map_unresolved(self, resolution: CurrentMapResolution) -> None: ...

    def on_watch_note(self, message: str) -> None: ...


def game_process_running(report: ProcessProbeReport) -> bool:
    """Return whether a usable probe observed at least one game process."""
    return report.available and bool(report.processes)


def companion_transition(
    previous: bool | None,
    running: bool,
) -> CompanionEvent | None:
    """Return the edge between two observations, or None without a baseline."""
    if previous is None or previous == running:
        return None
    return CompanionEvent.GAME_STARTED if running else CompanionEvent.GAME_EXITED


def source_key(path: Path) -> str:
    """Normalize one map path for equality across probe and load sessions."""
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def run_companion_watch(
    cancellation: threading.Event,
    *,
    roots_provider: Callable[[], tuple[Path, ...]],
    probe: Callable[[], ProcessProbeReport],
    locate: MapLocator,
    snapshot_factory: SnapshotFactory,
    loaded_source: Callable[[], str | None],
    hooks: CompanionHooks,
    interval_seconds: float,
    sleep: Callable[[float], bool],
) -> None:
    """Poll game presence until cancelled, pushing hook events off the Tk thread.

    ``sleep`` must return the cancellation state like ``Event.wait`` so an
    empty interval still stops promptly. One unusable probe only re-baselines
    the watcher, so probe recovery never fabricates a started/exit edge.
    Direct-evidence hits auto-load; hint-only candidate sets reach
    ``on_map_unresolved`` once per distinct set so the GUI can ask instead
    of guessing from recency.
    """
    previous: bool | None = None
    unresolved_key: str | None = None
    while not cancellation.is_set():
        report = probe()
        if not report.available:
            previous = None
            unresolved_key = None
            hooks.on_watch_note(_PROBE_UNAVAILABLE_NOTE)
        else:
            running = game_process_running(report)
            match companion_transition(previous, running):
                case CompanionEvent.GAME_STARTED:
                    hooks.on_game_started()
                case CompanionEvent.GAME_EXITED:
                    unresolved_key = None
                    hooks.on_game_exited()
                case None:
                    pass
                case unreachable:
                    assert_never(unreachable)
            previous = running
            if running:
                unresolved_key = _watch_running_map(
                    roots_provider(),
                    report,
                    locate,
                    snapshot_factory,
                    loaded_source,
                    hooks,
                    unresolved_key,
                )
        if sleep(interval_seconds):
            break


def _watch_running_map(
    roots: tuple[Path, ...],
    report: ProcessProbeReport,
    locate: MapLocator,
    snapshot_factory: SnapshotFactory,
    loaded_source: Callable[[], str | None],
    hooks: CompanionHooks,
    unresolved_key: str | None,
) -> str | None:
    """Resolve one live map; auto-load direct hits, surface hint sets once."""
    try:
        resolution = locate(roots, report)
    except Exception:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK - keep the watch loop alive.
        hooks.on_watch_note(_LOCATE_FAILED_NOTE)
        return unresolved_key
    candidates = resolution.candidates
    if resolution.status is ResolutionStatus.FOUND:
        if len(candidates) != 1:
            if loaded_source() is None:
                hooks.on_watch_note(_RUNNING_NO_HINTS_NOTE)
            return unresolved_key
        candidate = candidates[0]
        if loaded_source() == source_key(candidate.path):
            return unresolved_key
        try:
            snapshot = snapshot_factory(candidate.path)
        except OSError:
            hooks.on_watch_note(_SNAPSHOT_FAILED_NOTE)
            return unresolved_key
        hooks.on_map_ready(snapshot)
        return unresolved_key
    if resolution.status not in _PRESENTABLE_STATUSES or not candidates:
        if loaded_source() is None:
            hooks.on_watch_note(_RUNNING_NO_HINTS_NOTE)
        return unresolved_key
    loaded = loaded_source()
    if loaded is not None and any(
        source_key(candidate.path) == loaded for candidate in candidates
    ):
        return unresolved_key
    key = "|".join(sorted(source_key(candidate.path) for candidate in candidates))
    if key == unresolved_key:
        return unresolved_key
    hooks.on_map_unresolved(resolution)
    return key


__all__ = (
    "CompanionEvent",
    "CompanionHooks",
    "MapLocator",
    "SnapshotFactory",
    "companion_transition",
    "game_process_running",
    "run_companion_watch",
    "source_key",
)
