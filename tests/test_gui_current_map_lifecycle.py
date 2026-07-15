from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from threading import Event, Thread

import pytest

from tests.gui_base import GuiTestCase
from w3xtool import gui_current_map as current_gui
from w3xtool.gui_current_map import CurrentMapGuiMixin
from w3xtool.gui_current_map_presenter import SnapshotReady
from w3xtool.current_map_models import CurrentMapResolution, ResolutionStatus
from w3xtool.current_map_snapshot import CurrentMapSnapshot
from w3xtool.gui_lifecycle import GuiLifecycleMixin
from w3xtool.gui_worker_host import GuiWorkerHostMixin
from w3xtool.gui_worker_registry import GuiWorkerRegistry


class _Widget:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def configure(self, **values: str) -> None:
        self.values.update(values)

    def cget(self, key: str) -> str:
        return self.values.get(key, "")


class _Harness(CurrentMapGuiMixin, GuiWorkerHostMixin):
    def __init__(self) -> None:
        self._cur_dir = {"battle": None, "campaign": None}
        self.current_map_button = _Widget()
        self.status = _Widget()
        self.scheduled: list[Callable[[], None]] = []
        self._init_gui_worker_host()
        self._init_current_map_gui()

    def _load_config(self) -> Mapping[str, str | None]:
        return {}

    def after(self, delay_ms: int, callback: Callable[[], None]) -> str:
        _ = delay_ms
        self.scheduled.append(callback)
        return f"after-{len(self.scheduled)}"

    def after_cancel(self, poll_id: str) -> None:
        _ = poll_id
        return


def _snapshot(path: Path) -> CurrentMapSnapshot:
    return CurrentMapSnapshot(
        path=path,
        source_path=path,
        sha256="0" * 64,
        source_device=1,
        source_inode=1,
        source_size=0,
        source_mtime_ns=0,
        _directory_device=1,
        _directory_inode=1,
    )


class _LifecycleHarness(GuiLifecycleMixin):
    def __init__(self, events: list[str]) -> None:
        self._events = events
        self._casc_browser_dialog = None
        self.icons = self

    def close(self) -> None:
        self._events.append("resolver")

    def _shutdown_background_loader(self) -> None:
        self._events.append("loader")

    def _shutdown_object_filter_runner(self) -> None:
        return

    def _shutdown_gui_worker_host(self, timeout_seconds: float) -> tuple[str, ...]:
        assert timeout_seconds == 1.5
        self._events.append("workers")
        return ()

    def _save_layout_state(self, **_values: str) -> None:
        return

    def geometry(self) -> str:
        return "100x100"

    def _shutdown_current_map_gui(self) -> None:
        self._events.append("snapshots")

    def destroy(self) -> None:
        self._events.append("destroy")


class CurrentMapAppInitializationTest(GuiTestCase):
    def test_app_initializes_current_map_session(self) -> None:
        # Given/When: App has completed its normal constructor.
        # Then: current-map lifecycle state is ready before interaction.
        self.assertIs(self.app._current_map_initialized, True)

    def test_app_initializes_shared_worker_registry(self) -> None:
        # Given/When: App has completed its normal constructor.
        # Then: every worker-producing mixin shares one live registry.
        self.assertIsInstance(self.app._gui_workers, GuiWorkerRegistry)


def test_initialization_cleans_stale_snapshots_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: stale cleanup is observable at the GUI session boundary.
    calls: list[str] = []
    monkeypatch.setattr(
        current_gui,
        "cleanup_stale_current_map_snapshots",
        lambda: calls.append("cleanup"),
    )

    # When: initialization is requested twice for one app session.
    harness = _Harness()
    harness._init_current_map_gui()

    # Then: abandoned snapshots are scanned exactly once.
    assert calls == ["cleanup"]


def test_duplicate_click_is_ignored_while_worker_is_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a daemon worker that remains pending after it starts.
    monkeypatch.setattr(
        current_gui, "cleanup_stale_current_map_snapshots", lambda: None
    )
    harness = _Harness()
    workers: list[bool] = []

    class _DeferredThread:
        def __init__(
            self,
            *,
            target: Callable[[], None],
            daemon: bool,
            name: str,
        ) -> None:
            _ = target, name
            workers.append(daemon)

        def start(self) -> None:
            return

        def join(self, timeout: float | None = None) -> None:
            _ = timeout

        def is_alive(self) -> bool:
            return True

    harness._gui_workers = GuiWorkerRegistry(thread_factory=_DeferredThread)

    # When: the user clicks twice before the first result arrives.
    harness.on_open_current_map()
    harness.on_open_current_map()

    # Then: only one daemon worker and one polling loop exist.
    assert workers == [True]
    assert len(harness.scheduled) == 1


def test_shutdown_cleans_session_owned_snapshot_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a snapshot has been adopted by the active GUI session.
    monkeypatch.setattr(
        current_gui, "cleanup_stale_current_map_snapshots", lambda: None
    )
    harness = _Harness()
    snapshot = _snapshot(tmp_path / "current.w3x")
    cleaned: list[CurrentMapSnapshot] = []
    monkeypatch.setattr(current_gui, "cleanup_current_map_snapshot", cleaned.append)
    assert harness._adopt_current_map_snapshot(0, snapshot)

    # When: current-map lifecycle shutdown runs twice.
    harness._shutdown_current_map_gui()
    harness._shutdown_current_map_gui()

    # Then: ownership is released exactly once.
    assert cleaned == [snapshot]


def test_app_close_releases_snapshots_after_resolver_before_destroy() -> None:
    # Given: each shutdown boundary records its order.
    events: list[str] = []
    harness = _LifecycleHarness(events)

    # When: the application close boundary runs.
    harness._on_close()

    # Then: delayed resolver reads end before snapshots are removed.
    assert events == ["loader", "workers", "resolver", "snapshots", "destroy"]


def test_worker_finishing_after_shutdown_cleans_new_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: snapshot creation is blocked before ownership transfer.
    monkeypatch.setattr(
        current_gui, "cleanup_stale_current_map_snapshots", lambda: None
    )
    harness = _Harness()
    snapshot = _snapshot(tmp_path / "current.w3x")
    started = Event()
    release = Event()
    cleaned: list[CurrentMapSnapshot] = []

    def create_snapshot(_path: Path) -> CurrentMapSnapshot:
        started.set()
        assert release.wait(2)
        return snapshot

    monkeypatch.setattr(current_gui, "cleanup_current_map_snapshot", cleaned.append)
    worker = Thread(
        target=current_gui.run_snapshot,
        args=(
            0,
            tmp_path / "source.w3x",
            create_snapshot,
            harness._put_current_map_event,
            harness._put_current_map_snapshot,
        ),
        daemon=True,
    )
    worker.start()
    assert started.wait(2)

    # When: shutdown wins the lock before the worker finishes.
    harness._shutdown_current_map_gui()
    release.set()
    worker.join(2)

    # Then: the worker reclaims its unadopted snapshot without queueing it.
    assert not worker.is_alive()
    assert cleaned == [snapshot]
    assert harness._current_map_snapshots == []
    assert harness._current_map_results.empty()


def test_blocked_discovery_is_tracked_and_late_resolution_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    monkeypatch.setattr(
        current_gui, "cleanup_stale_current_map_snapshots", lambda: None
    )
    harness = _Harness()
    started = Event()
    release = Event()
    finished = Event()

    def locate(_roots: tuple[Path, ...]) -> CurrentMapResolution:
        started.set()
        assert release.wait(2)
        finished.set()
        return CurrentMapResolution(ResolutionStatus.NOT_FOUND, ())

    monkeypatch.setattr(current_gui, "locate_current_map", locate)
    harness.on_open_current_map()
    assert started.wait(1)

    # When
    harness._shutdown_current_map_gui()
    lingering = harness._shutdown_gui_worker_host(0)
    release.set()
    assert finished.wait(1)

    # Then
    assert lingering == ("current-map",)
    assert harness._current_map_results.empty()
    assert harness._shutdown_gui_worker_host(1) == ()


def test_stale_snapshot_event_is_removed_and_cleaned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: an owned snapshot event belongs to an obsolete generation.
    monkeypatch.setattr(
        current_gui, "cleanup_stale_current_map_snapshots", lambda: None
    )
    harness = _Harness()
    snapshot = _snapshot(tmp_path / "current.w3x")
    cleaned: list[CurrentMapSnapshot] = []
    monkeypatch.setattr(current_gui, "cleanup_current_map_snapshot", cleaned.append)
    assert harness._adopt_current_map_snapshot(0, snapshot)
    harness._current_map_results.put((-1, SnapshotReady(snapshot)))

    # When: UI polling discards the stale event.
    harness._poll_current_map_results()

    # Then: it cannot leak or become a load request.
    assert cleaned == [snapshot]
    assert harness._current_map_snapshots == []
