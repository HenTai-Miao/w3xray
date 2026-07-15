"""Off-thread discovery and snapshot work for current-map GUI acquisition."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
import threading
from typing import TYPE_CHECKING, assert_never

from .current_map_models import CurrentMapResolution, ResolutionStatus
from .current_map_snapshot import CurrentMapSnapshot
from .gui_current_map_presenter import (
    CurrentMapEvent,
    ResolutionReady,
    SnapshotReady,
    WorkerError,
)


type EventSink = Callable[[int, ResolutionReady | WorkerError], None]
type SnapshotSink = Callable[[int, CurrentMapSnapshot], None]
type Locator = Callable[[tuple[Path, ...]], CurrentMapResolution]
type SnapshotFactory = Callable[[Path], CurrentMapSnapshot]
type SnapshotCleanup = Callable[[CurrentMapSnapshot], None]


if TYPE_CHECKING:
    import queue
    from typing import Protocol

    from .gui_worker_registry import GuiWorkerTarget, GuiWorkerTicket

    class _Configurable(Protocol):
        def configure(self, **values: str) -> None: ...

        def cget(self, key: str) -> str | Callable[[], None]: ...

    class _TypingConfigurable:
        def configure(self, **values: str) -> None:
            return

        def cget(self, key: str) -> str:
            return key

    class CurrentMapHost:
        _current_map_initialized: bool = False
        _current_map_results: queue.Queue[tuple[int, CurrentMapEvent]] = queue.Queue()
        _current_map_lock: threading.Lock = threading.Lock()
        _current_map_generation: int = 0
        _current_map_pending: bool = False
        _current_map_stopped: bool = False
        _current_map_poll_id: str | None = None
        _current_map_snapshots: list[CurrentMapSnapshot] = []
        _cur_dir: Mapping[str, str | Path | None] = {}
        current_map_button: _Configurable = _TypingConfigurable()
        status: _Configurable = _TypingConfigurable()

        def _load_config(self) -> Mapping[str, str | Path | None]: ...

        def _start_path_load(self, path: str) -> None: ...

        def after(self, delay_ms: int, callback: Callable[[], None]) -> str: ...

        def after_cancel(self, after_id: str) -> None: ...

        def _start_gui_worker(
            self,
            group: str,
            target: GuiWorkerTarget,
            *,
            replace: bool,
        ) -> GuiWorkerTicket: ...

        def _cancel_gui_worker_group(self, group: str) -> None: ...
else:
    CurrentMapHost = object


def collect_extra_roots(
    current: Mapping[str, str | Path | None],
    persisted: Mapping[str, str | Path | None],
) -> tuple[Path, ...]:
    """Collect current and persisted map roots in deterministic priority order."""
    raw_roots = tuple(current.get(key) for key in ("battle", "campaign"))
    raw_roots += tuple(
        persisted.get(key)
        for key in ("last_dir_battle", "last_dir_campaign", "last_dir")
    )
    roots: list[Path] = []
    seen: set[str] = set()
    for raw_root in raw_roots:
        match raw_root:
            case Path() as value:
                root = Path(value)
            case str() as value:
                if not value:
                    continue
                root = Path(value)
            case None:
                continue
            case unreachable:
                assert_never(unreachable)
        key = str(root)
        if key not in seen:
            seen.add(key)
            roots.append(root)
    return tuple(roots)


def run_discovery(
    generation: int,
    roots: tuple[Path, ...],
    locator: Locator,
    snapshot_factory: SnapshotFactory,
    event_sink: EventSink,
    snapshot_sink: SnapshotSink,
) -> None:
    """Resolve current-map evidence and emit only typed worker results."""
    try:
        resolution = locator(roots)
        match resolution.status:
            case ResolutionStatus.FOUND:
                if len(resolution.candidates) != 1:
                    event_sink(generation, WorkerError())
                    return
                run_snapshot(
                    generation,
                    resolution.candidates[0].path,
                    snapshot_factory,
                    event_sink,
                    snapshot_sink,
                )
            case (
                ResolutionStatus.AMBIGUOUS
                | ResolutionStatus.SUGGESTED
                | ResolutionStatus.NOT_FOUND
                | ResolutionStatus.UNAVAILABLE
            ):
                event_sink(generation, ResolutionReady(resolution))
            case unreachable:
                assert_never(unreachable)
    except Exception:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK - stable worker event.
        event_sink(generation, WorkerError())


def run_snapshot(
    generation: int,
    path: Path,
    snapshot_factory: SnapshotFactory,
    event_sink: EventSink,
    snapshot_sink: SnapshotSink,
) -> None:
    """Create a stable snapshot and transfer it through the ownership sink."""
    try:
        snapshot_sink(generation, snapshot_factory(path))
    except Exception:  # noqa: BLE001  # noqa: BROAD_EXCEPT_OK - stable worker event.
        event_sink(generation, WorkerError())


def discard_event(
    event: CurrentMapEvent,
    lock: threading.Lock,
    owned_snapshots: list[CurrentMapSnapshot],
    cleanup: SnapshotCleanup,
) -> None:
    """Release resources carried by a stale UI event exactly once."""
    match event:
        case SnapshotReady(snapshot=snapshot):
            with lock:
                owned = snapshot in owned_snapshots
                if owned:
                    owned_snapshots.remove(snapshot)
            if owned:
                cleanup(snapshot)
        case ResolutionReady() | WorkerError():
            return
        case unreachable:
            assert_never(unreachable)
