"""Shared worker lifecycle coverage for map-directory scans."""

from __future__ import annotations

from collections.abc import Callable
import threading

import pytest

import gametool.gui_source_browser as source_browser
from gametool.gui_source_browser import SourceBrowserMixin
from gametool.gui_worker_host import GuiWorkerHostMixin


class _Status:
    def __init__(self) -> None:
        self.values: list[str] = []

    def configure(self, *, text: str) -> None:
        self.values.append(text)


class _SourceBrowser(SourceBrowserMixin, GuiWorkerHostMixin):
    _cur_dir: dict[str, str | None]  # pyright: ignore[reportIncompatibleVariableOverride] - 测试桩
    status: _Status  # pyright: ignore[reportIncompatibleVariableOverride] - 测试桩

    def __init__(self) -> None:
        self._cur_dir = {"battle": None, "campaign": None}
        self.status = _Status()  # pyright: ignore[reportIncompatibleVariableOverride] - 测试桩
        self.scheduled: dict[str, Callable[[], None]] = {}
        self.filled: list[tuple[tuple[str, str], ...]] = []
        self._next_after = 1
        self._init_gui_worker_host()

    def update_idletasks(self) -> None:
        return

    def after(  # pyright: ignore[reportIncompatibleMethodOverride] - 测试桩
        self, delay_ms: int, callback: Callable[[], None]
    ) -> str:
        assert delay_ms >= 0
        after_id = f"after-{self._next_after}"
        self._next_after += 1
        self.scheduled[after_id] = callback
        return after_id

    def after_cancel(self, after_id: str) -> None:  # pyright: ignore[reportIncompatibleMethodOverride] - 测试桩
        self.scheduled.pop(after_id, None)

    def _fill_battle(self, items: list[tuple[str, str]]) -> None:
        self.filled.append(tuple(items))


def test_scan_finishing_after_shutdown_never_updates_source_panel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    browser = _SourceBrowser()
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def scan(_directory: str) -> list[tuple[str, str]]:
        started.set()
        assert release.wait(2)
        finished.set()
        return [("/maps/a.w3x", "A")]

    monkeypatch.setattr(source_browser, "scan_battle_maps", scan)
    browser._scan_dir("/maps", "battle")
    assert started.wait(5)

    # When
    lingering = browser._shutdown_gui_worker_host(0)
    release.set()
    assert finished.wait(5)

    # Then
    assert lingering == ("source-scan",)
    assert browser.scheduled == {}
    assert browser.filled == []
    assert browser._shutdown_gui_worker_host(1) == ()
