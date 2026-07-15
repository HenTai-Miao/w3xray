from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
import pytest

from tests.gui_base import GuiTestCase
from w3xtool import gui_current_map as current_gui
from w3xtool.gui_current_map import CurrentMapGuiMixin
from w3xtool.current_map_models import (
    CurrentMapResolution,
    EvidenceKind,
    MapCandidate,
    MapEvidence,
    ResolutionStatus,
)
from w3xtool.current_map_snapshot import CurrentMapSnapshot
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
        self._root_values: dict[str, str | Path | None] = {
            "battle": "/current/battle",
            "campaign": None,
        }
        self._cur_dir = self._root_values
        self.config: dict[str, str | None] = {}
        self._button = _Widget()
        self._status = _Widget()
        self.current_map_button = self._button
        self.status = self._status
        self.loaded: list[str] = []
        self.scheduled: list[Callable[[], None]] = []
        self.cancelled: list[str] = []
        self._init_gui_worker_host()
        self._gui_workers = GuiWorkerRegistry(thread_factory=_InlineThread)
        self._init_current_map_gui()

    def _load_config(self) -> Mapping[str, str | None]:
        return self.config

    def _start_path_load(self, path: str) -> None:
        self.loaded.append(path)
        self.status.configure(text="正在解析当前地图")

    def after(self, delay_ms: int, callback: Callable[[], None]) -> str:
        _ = delay_ms
        self.scheduled.append(callback)
        return f"after-{len(self.scheduled)}"

    def after_cancel(self, after_id: str) -> None:
        self.cancelled.append(after_id)

    def set_campaign_root(self, path: str) -> None:
        self._root_values["campaign"] = path

    def button_state(self) -> str:
        return self._button.values["state"]

    def status_text(self) -> str:
        return self._status.values["text"]


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


def _candidate(path: Path, kind: EvidenceKind) -> MapCandidate:
    return MapCandidate(path, (MapEvidence(path, kind, 73),))


def _harness(monkeypatch: pytest.MonkeyPatch) -> _Harness:
    monkeypatch.setattr(
        current_gui, "cleanup_stale_current_map_snapshots", lambda: None
    )
    return _Harness()


class CurrentMapTopbarTest(GuiTestCase):
    def test_current_map_button_is_wired_beside_manual_open(self) -> None:
        # Given: the real GUI topbar has been constructed.
        # When: its current-map action is inspected.
        button = self.app.current_map_button

        # Then: the action is visible and delegates to the app handler.
        self.assertEqual(button.cget("text"), "获取当前地图")
        self.assertTrue(button.cget("command"))
        self.assertTrue(callable(self.app.on_open_current_map))


def test_direct_result_stays_queued_then_delegates_snapshot_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: current and persisted roots plus one process-linked map.
    harness = _harness(monkeypatch)
    harness.set_campaign_root("/current/campaign")
    harness.config = {
        "last_dir_battle": "/saved/battle",
        "last_dir_campaign": "/saved/campaign",
        "last_dir": "/saved/legacy",
    }
    source = tmp_path / "source.w3x"
    snapshot = _snapshot(tmp_path / "private" / "current.w3x")
    resolution = CurrentMapResolution(
        ResolutionStatus.FOUND,
        (_candidate(source, EvidenceKind.DIRECT_OPEN),),
    )
    roots_seen: list[tuple[Path, ...]] = []
    monkeypatch.setattr(
        current_gui,
        "locate_current_map",
        lambda roots: roots_seen.append(tuple(roots)) or resolution,
    )
    monkeypatch.setattr(
        current_gui, "create_current_map_snapshot", lambda _path: snapshot
    )

    # When: acquisition runs inline but the Tk polling boundary has not run yet.
    harness.on_open_current_map()

    # Then: no load occurs until polling; polling delegates only the private path.
    assert harness.loaded == []
    assert harness.button_state() == "disabled"
    harness._poll_current_map_results()
    assert roots_seen == [
        (
            Path("/current/battle"),
            Path("/current/campaign"),
            Path("/saved/battle"),
            Path("/saved/campaign"),
            Path("/saved/legacy"),
        )
    ]
    assert harness.loaded == [str(snapshot.path)]
    assert harness.button_state() == "normal"
    assert harness.status_text() == "正在解析当前地图"
