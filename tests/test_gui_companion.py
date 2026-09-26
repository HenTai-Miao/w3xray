from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
import threading

import pytest

from tests.gui_base import GuiTestCase
from w3xtool import gui_companion as companion_gui
from w3xtool.companion_watch import source_key
from w3xtool.current_map_models import (
    CurrentMapResolution,
    GameProcess,
    MapCandidate,
    ResolutionStatus,
)
from w3xtool.current_map_process import ProcessProbeReport
from w3xtool.current_map_snapshot import CurrentMapSnapshot
from w3xtool.gui_companion import CompanionGuiMixin
from w3xtool.gui_current_map_presenter import AcceptedSuggestion, TerminalStatus
from w3xtool.gui_worker_host import GuiWorkerHostMixin
from w3xtool.gui_worker_registry import GuiWorkerRegistry


class _Widget:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def configure(self, **values: str) -> None:
        self.values.update(values)

    def cget(self, key: str) -> str:
        return self.values.get(key, "")


class _Tabs:
    def __init__(self) -> None:
        self.selected: list[str] = []

    def set(self, name: str) -> None:
        self.selected.append(name)


class _InlineThread:
    def __init__(
        self,
        *,
        target: Callable[[], None],
        daemon: bool,
        name: str,
    ) -> None:
        self._target = target
        self.daemon = daemon
        self.name = name

    def start(self) -> None:
        self._target()

    def join(self, timeout: float | None = None) -> None:
        _ = timeout

    def is_alive(self) -> bool:
        return False


class _Harness(CompanionGuiMixin, GuiWorkerHostMixin):
    def __init__(self, config: Mapping[str, str | None] | None = None) -> None:
        self._cur_dir: Mapping[str, str | Path | None] = {
            "battle": None,
            "campaign": None,
        }
        self._config: dict[str, str | None] = dict(config) if config else {}
        self._button = _Widget()
        self._status = _Widget()
        self._tabs = _Tabs()
        self.companion_button = self._button
        self.status = self._status
        self.tabs = self._tabs
        self.loaded: list[str] = []
        self.saved: list[dict[str, object]] = []
        self.scheduled: list[Callable[[], None]] = []
        self._current_map_lock = threading.Lock()
        self._current_map_pending = False
        self._current_map_snapshots: list[CurrentMapSnapshot] = []
        self._init_gui_worker_host()
        self._gui_workers = GuiWorkerRegistry(thread_factory=_InlineThread)
        self._init_companion()
        self._button.configure(text=self._companion_button_label())

    def _load_config(self) -> Mapping[str, str | None]:
        return self._config

    def _save_config(self, **values: object) -> None:
        self.saved.append(values)

    def _start_path_load(self, path: str) -> None:
        self.loaded.append(path)

    def after(self, delay_ms: int, callback: Callable[[], None]) -> str:
        _ = delay_ms
        self.scheduled.append(callback)
        return f"after-{len(self.scheduled)}"

    def after_cancel(self, after_id: str) -> None:
        _ = after_id

    def button_text(self) -> str:
        return self._button.values["text"]

    def status_text(self) -> str:
        return self._status.values.get("text", "")

    def deliver_posts(self) -> None:
        self._poll_gui_posts()


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


def _report(processes: int = 0, available: bool = True) -> ProcessProbeReport:
    return ProcessProbeReport(
        tuple(GameProcess(100 + index, "war3.exe", "") for index in range(processes)),
        available,
    )


def test_toggle_persists_state_and_wires_the_watch_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_watch(cancellation: threading.Event, **kwargs: object) -> None:
        captured["cancellation"] = cancellation
        captured.update(kwargs)

    monkeypatch.setattr(companion_gui, "run_companion_watch", fake_watch)
    harness = _Harness()

    harness.on_toggle_companion()

    assert harness.saved == [{"companion_enabled": True}]
    assert harness.button_text() == companion_gui._COMPANION_ON_LABEL
    assert harness.status_text() == "魔兽联动已开启：等待魔兽启动 …"
    assert captured["probe"] is companion_gui.probe_game_processes
    assert captured["locate"] is companion_gui._locate_with_probe
    assert captured["snapshot_factory"] is companion_gui.create_current_map_snapshot
    assert captured["interval_seconds"] == 5.0
    assert isinstance(captured["cancellation"], threading.Event)

    harness.on_toggle_companion()

    assert harness.saved[-1] == {"companion_enabled": False}
    assert harness.button_text() == companion_gui._COMPANION_OFF_LABEL
    assert harness.status_text() == "魔兽联动已关闭"


def test_enabled_config_starts_one_watch_and_startups_are_deduplicated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runs: list[dict[str, object]] = []

    def fake_watch(cancellation: threading.Event, **kwargs: object) -> None:
        _ = cancellation
        runs.append(dict(kwargs))

    monkeypatch.setattr(companion_gui, "run_companion_watch", fake_watch)
    harness = _Harness({"companion_enabled": "1"})

    assert harness._companion_enabled is True
    assert harness.button_text() == companion_gui._COMPANION_ON_LABEL

    harness._start_companion_watch_if_enabled()
    harness._start_companion_watch_if_enabled()

    assert len(runs) == 1
    assert runs[0]["interval_seconds"] == 5.0


def test_map_ready_loads_snapshot_and_focuses_relations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cleaned: list[CurrentMapSnapshot] = []
    monkeypatch.setattr(companion_gui, "cleanup_current_map_snapshot", cleaned.append)
    harness = _Harness()
    first = _snapshot(tmp_path / "a.w3x")
    second = _snapshot(tmp_path / "b.w3x")

    harness._on_companion_map_ready(first)

    assert harness.loaded == [str(first.path)]
    assert harness._tabs.selected == ["掉落/获取"]
    assert harness._companion_loaded_source_key() == source_key(first.source_path)
    assert first.source_path.name in harness.status_text()

    harness._on_companion_map_ready(second)

    assert cleaned == [first]
    assert harness.loaded[-1] == str(second.path)


def test_game_exit_retires_snapshot_and_rearms_for_next_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cleaned: list[CurrentMapSnapshot] = []
    monkeypatch.setattr(companion_gui, "cleanup_current_map_snapshot", cleaned.append)
    harness = _Harness()
    snapshot = _snapshot(tmp_path / "a.w3x")
    harness._on_companion_map_ready(snapshot)
    cleaned.clear()

    harness._on_companion_game_exited()

    assert cleaned == [snapshot]
    assert harness._companion_loaded_source_key() is None
    assert harness.status_text() == "魔兽已退出，联动待命 …"


def test_shutdown_stops_watching_and_releases_owned_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cleaned: list[CurrentMapSnapshot] = []
    monkeypatch.setattr(companion_gui, "cleanup_current_map_snapshot", cleaned.append)
    harness = _Harness()
    first = _snapshot(tmp_path / "a.w3x")
    second = _snapshot(tmp_path / "b.w3x")
    harness._on_companion_map_ready(first)
    cleaned.clear()

    harness._shutdown_companion()
    harness._shutdown_companion()

    assert cleaned == [first]

    harness._on_companion_map_ready(second)

    assert cleaned == [first, second]
    assert harness.loaded == [str(first.path)]

    harness.on_toggle_companion()

    assert harness.saved == []


def test_watch_loop_posts_events_that_land_on_the_tk_thread(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cleaned: list[CurrentMapSnapshot] = []
    monkeypatch.setattr(companion_gui, "cleanup_current_map_snapshot", cleaned.append)
    snapshot = _snapshot(tmp_path / "live.w3x")
    resolution = CurrentMapResolution(
        ResolutionStatus.FOUND,
        (MapCandidate(Path("/maps/live.w3x"), ()),),
    )
    monkeypatch.setattr(
        companion_gui,
        "locate_current_map",
        lambda roots, process_provider=None: resolution,
    )
    monkeypatch.setattr(
        companion_gui,
        "create_current_map_snapshot",
        lambda _path: snapshot,
    )
    monkeypatch.setattr(companion_gui, "_COMPANION_POLL_SECONDS", 0.0)
    harness = _Harness()
    ticket = harness._gui_workers.start(
        "companion", lambda _ticket: None, replace=False
    )
    reports = [_report(available=False), _report(processes=1)]

    def fake_probe() -> ProcessProbeReport:
        if not reports:
            ticket.cancellation.set()
            return _report()
        return reports.pop(0)

    monkeypatch.setattr(companion_gui, "probe_game_processes", fake_probe)

    harness._run_companion_watch_target(ticket)
    harness.deliver_posts()

    assert harness.loaded == [str(snapshot.path)]
    assert harness._tabs.selected == ["掉落/获取"]
    assert cleaned == [snapshot]
    assert harness.status_text() == "魔兽已退出，联动待命 …"
    assert harness._companion_loaded_source_key() is None


def test_map_unresolved_loads_the_accepted_choice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cleaned: list[CurrentMapSnapshot] = []
    monkeypatch.setattr(companion_gui, "cleanup_current_map_snapshot", cleaned.append)
    snapshot = _snapshot(tmp_path / "picked.w3x")
    monkeypatch.setattr(
        companion_gui,
        "create_current_map_snapshot",
        lambda _path: snapshot,
    )
    monkeypatch.setattr(
        companion_gui,
        "present_resolution",
        lambda _resolution: AcceptedSuggestion(Path("/maps/live.w3x")),
    )
    harness = _Harness()

    harness._on_companion_map_unresolved(
        CurrentMapResolution(
            ResolutionStatus.SUGGESTED,
            (MapCandidate(Path("/maps/live.w3x"), ()),),
        )
    )
    harness.deliver_posts()

    assert harness.loaded == [str(snapshot.path)]
    assert harness._tabs.selected == ["掉落/获取"]
    assert harness._companion_loaded_source_key() == source_key(snapshot.source_path)
    assert cleaned == []


def test_map_unresolved_decline_reports_status_without_loading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        companion_gui,
        "present_resolution",
        lambda _resolution: TerminalStatus("已取消获取当前地图"),
    )
    harness = _Harness()

    harness._on_companion_map_unresolved(
        CurrentMapResolution(ResolutionStatus.SUGGESTED, ())
    )

    assert harness.loaded == []
    assert harness.status_text() == "已取消获取当前地图"


def test_map_unresolved_waits_while_manual_acquisition_is_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    presented: list[object] = []

    def fake_present(resolution: object) -> TerminalStatus:
        presented.append(resolution)
        return TerminalStatus("已取消获取当前地图")

    monkeypatch.setattr(companion_gui, "present_resolution", fake_present)
    harness = _Harness()
    harness._current_map_pending = True

    harness._on_companion_map_unresolved(
        CurrentMapResolution(ResolutionStatus.SUGGESTED, ())
    )

    assert presented == []
    assert harness.status_text() == ""


def test_companion_load_failure_reports_a_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(_path: Path) -> CurrentMapSnapshot:
        raise OSError("snapshot denied")

    monkeypatch.setattr(companion_gui, "create_current_map_snapshot", fail)
    monkeypatch.setattr(
        companion_gui,
        "present_resolution",
        lambda _resolution: AcceptedSuggestion(Path("/maps/live.w3x")),
    )
    harness = _Harness()

    harness._on_companion_map_unresolved(
        CurrentMapResolution(
            ResolutionStatus.SUGGESTED,
            (MapCandidate(Path("/maps/live.w3x"), ()),),
        )
    )
    harness.deliver_posts()

    assert harness.loaded == []
    assert harness.status_text() == companion_gui._COMPANION_LOAD_FAILED_NOTE


def test_loaded_source_prefers_companion_state_then_manual_snapshots(
    tmp_path: Path,
) -> None:
    harness = _Harness()
    snapshot = _snapshot(tmp_path / "manual.w3x")

    assert harness._companion_loaded_source_key() is None

    harness._current_map_snapshots.append(snapshot)

    assert harness._companion_loaded_source_key() == source_key(snapshot.source_path)

    companion_snapshot = _snapshot(tmp_path / "companion.w3x")
    harness._on_companion_map_ready(companion_snapshot)

    assert harness._companion_loaded_source_key() == source_key(
        companion_snapshot.source_path
    )


class CompanionTopbarWiringTest(GuiTestCase):
    def test_companion_button_is_wired_in_topbar(self) -> None:
        button = self.app.companion_button

        self.assertIn(button.cget("text"), ("魔兽联动：开", "魔兽联动：关"))
        self.assertTrue(button.cget("command"))
        self.assertTrue(callable(self.app.on_toggle_companion))

    def test_app_initializes_companion_state(self) -> None:
        self.assertIs(self.app._companion_initialized, True)
