"""Shared worker lifecycle coverage for real-save analysis."""

from __future__ import annotations

from collections.abc import Callable
import threading

import pytest

import w3xtool.gui_external_data as external_data
from w3xtool.api import MapData
from w3xtool.gui_external_data import ExternalDataToolsMixin
from w3xtool.gui_worker_host import GuiWorkerHostMixin
from w3xtool.real_save_files import RealSaveReport


class _Status:
    def __init__(self) -> None:
        self.values: list[str] = []

    def configure(self, *, text: str) -> None:
        self.values.append(text)


class _ExternalData(ExternalDataToolsMixin, GuiWorkerHostMixin):
    def __init__(self) -> None:
        self.map_data = MapData(path="map.w3x", name="map")
        self.status = _Status()
        self.scheduled: list[Callable[[], None]] = []
        self.opened: list[tuple[str, int, str]] = []
        self._init_gui_worker_host()

    def after(self, delay_ms: int, callback: Callable[[], None]) -> str:
        assert delay_ms == 0
        self.scheduled.append(callback)
        return f"after-{len(self.scheduled)}"

    def _open_dir(self, output: str, count: int, kind: str) -> None:
        self.opened.append((output, count, kind))


def test_save_analysis_finishing_after_shutdown_never_opens_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    harness = _ExternalData()
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def analyze(path: str, _md: MapData) -> RealSaveReport:
        started.set()
        assert release.wait(2)
        finished.set()
        return RealSaveReport(path, (), ())

    monkeypatch.setattr(
        external_data, "tmp_extract_dir", lambda *_args, **_kwargs: "/tmp/out"
    )
    monkeypatch.setattr(external_data, "analyze_real_save_path", analyze)
    monkeypatch.setattr(external_data, "write_text", lambda *_args: 1)
    harness._start_real_save_analysis("/saves")
    assert started.wait(1)

    # When
    lingering = harness._shutdown_gui_worker_host(0)
    release.set()
    assert finished.wait(1)

    # Then
    assert lingering == ("real-save-analysis",)
    assert harness.scheduled == []
    assert harness.opened == []
    assert harness.status.values == ["正在只读分析真实存档 …"]
    assert harness._shutdown_gui_worker_host(1) == ()
