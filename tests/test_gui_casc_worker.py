"""Shared worker lifecycle coverage for opening CASC inventory sources."""

from __future__ import annotations

from collections.abc import Callable, Iterator
import threading

import pytest

import w3xtool.gui_casc_browser as casc_gui
from w3xtool.casclib_enumeration import CascEntry
from w3xtool.game_data_inventory import GameDataInventoryView
from w3xtool.gui_casc_browser import CascBrowserMixin
from w3xtool.gui_worker_host import GuiWorkerHostMixin


class _Status:
    def __init__(self) -> None:
        self.values: list[str] = []

    def configure(self, *, text: str) -> None:
        self.values.append(text)


class _InventorySource:
    inventory_view = GameDataInventoryView.KNOWN_PATHS

    def __init__(self) -> None:
        self.closed = threading.Event()

    def has_file(self, _name: str) -> bool:
        return True

    def read_file(self, _name: str) -> bytes:
        return b"data"

    def iter_entries(
        self,
        _mask: str = "*",
        _listfile: str | None = None,
    ) -> Iterator[CascEntry]:
        return iter(())

    def close(self) -> None:
        self.closed.set()


class _CascHost(CascBrowserMixin, GuiWorkerHostMixin):
    def __init__(self) -> None:
        self.game_data_path = "/game-data"
        self.status = _Status()
        self.scheduled: list[Callable[[], None]] = []
        self.shown: list[_InventorySource] = []
        self._init_gui_worker_host()

    def after(self, delay_ms: int, callback: Callable[[], None]) -> str:
        assert delay_ms == 0
        self.scheduled.append(callback)
        return f"after-{len(self.scheduled)}"

    def _show_casc_browser(self, source: _InventorySource) -> None:
        self.shown.append(source)


def test_casc_source_arriving_after_shutdown_is_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    host = _CascHost()
    source = _InventorySource()
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def open_source(_path: str) -> _InventorySource:
        started.set()
        assert release.wait(2)
        finished.set()
        return source

    monkeypatch.setattr(casc_gui, "open_game_data_source", open_source)
    host.on_browse_game_data()
    assert started.wait(1)

    # When
    lingering = host._shutdown_gui_worker_host(0)
    release.set()
    assert finished.wait(1)

    # Then
    assert lingering == ("casc-open",)
    assert source.closed.wait(1)
    assert host.scheduled == []
    assert host.shown == []
    assert host._shutdown_gui_worker_host(1) == ()
