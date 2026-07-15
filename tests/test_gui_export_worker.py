"""Shared worker lifecycle coverage for GUI exports."""

from __future__ import annotations

from collections.abc import Callable
import threading

import pytest

import w3xtool.gui_export_actions as export_actions
from w3xtool.api import MapData
from w3xtool.gui_export_actions import ExportActionsMixin
from w3xtool.gui_worker_host import GuiWorkerHostMixin


class _Status:
    def __init__(self) -> None:
        self.values: list[str] = []

    def configure(self, *, text: str) -> None:
        self.values.append(text)


class _Exporter(ExportActionsMixin, GuiWorkerHostMixin):
    def __init__(self) -> None:
        self.map_data = MapData(path="map.w3x", name="map")
        self.map_data.scripts = {"war3map.j": "script"}
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


def test_script_export_finishing_after_shutdown_never_opens_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    exporter = _Exporter()
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def write_scripts(_scripts, _output: str) -> int:
        started.set()
        assert release.wait(2)
        finished.set()
        return 1

    monkeypatch.setattr(
        export_actions, "tmp_extract_dir", lambda *_args, **_kwargs: "/tmp/scripts"
    )
    monkeypatch.setattr(export_actions, "write_script_exports", write_scripts)
    exporter.on_export_scripts()
    assert started.wait(1)

    # When
    lingering = exporter._shutdown_gui_worker_host(0)
    release.set()
    assert finished.wait(1)

    # Then
    assert lingering == ("export-scripts",)
    assert exporter.scheduled == []
    assert exporter.opened == []
    assert exporter.status.values == ["正在导出脚本 …"]
    assert exporter._shutdown_gui_worker_host(1) == ()
