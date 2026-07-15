"""Shared worker lifecycle tests for object filtering."""

from __future__ import annotations

from collections.abc import Callable
import threading
from typing import assert_never

import pytest

import w3xtool.gui_object_filter_runner as filter_runner
from w3xtool.api import MapData
from w3xtool.gui_object_filter_runner import ObjectFilterError, ObjectFilterRunnerMixin
from w3xtool.gui_worker_host import GuiWorkerHostMixin
from w3xtool.object_filter import ObjectFilterResult


class _Search:
    def __init__(self) -> None:
        self.value = ""

    def get(self) -> str:
        return self.value


class _Status:
    def __init__(self) -> None:
        self.values: list[str] = []

    def configure(self, *, text: str) -> None:
        self.values.append(text)


class _FilterRunner(ObjectFilterRunnerMixin, GuiWorkerHostMixin):
    def __init__(self) -> None:
        self.map_data = MapData(path="map.w3x", name="map")
        self.search_var = _Search()
        self.status = _Status()
        self.scheduled: dict[str, Callable[[], None]] = {}
        self.posted = threading.Event()
        self.handled: list[ObjectFilterResult] = []
        self._next_after = 1
        self._init_gui_worker_host()
        self._init_object_filter_runner()

    def after(self, delay_ms: int, callback: Callable[[], None]) -> str:
        _ = delay_ms
        poll_id = f"after-{self._next_after}"
        self._next_after += 1
        self.scheduled[poll_id] = callback
        self.posted.set()
        return poll_id

    def after_cancel(self, poll_id: str) -> None:
        self.scheduled.pop(poll_id, None)

    def _handle_object_filter_payload(
        self,
        payload: filter_runner.ObjectFilterPayload,
    ) -> None:
        match payload:
            case ObjectFilterResult() as result:
                self.handled.append(result)
            case ObjectFilterError():
                return
            case unreachable:
                assert_never(unreachable)

    def run_scheduled(self) -> None:
        callbacks = tuple(self.scheduled.values())
        self.scheduled.clear()
        for callback in callbacks:
            callback()


def _result(label: str) -> ObjectFilterResult:
    return ObjectFilterResult({}, (label,))


def test_shutdown_tracks_blocked_filter_and_prevents_late_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    runner = _FilterRunner()
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def block(_md: MapData, _query: str) -> ObjectFilterResult:
        started.set()
        assert release.wait(2)
        finished.set()
        return _result("late")

    monkeypatch.setattr(filter_runner, "filter_objects_by_query", block)
    runner._refresh_list()
    assert started.wait(1)

    # When
    runner._shutdown_object_filter_runner()
    lingering = runner._shutdown_gui_worker_host(0)
    release.set()
    assert finished.wait(1)

    # Then
    assert lingering == ("object-filter",)
    assert runner.scheduled == {}
    assert runner.handled == []
    assert runner.status.values == ["正在筛选对象 …"]
    assert runner._shutdown_gui_worker_host(1) == ()


def test_replaced_filter_only_delivers_current_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    runner = _FilterRunner()
    first_started = threading.Event()
    release_first = threading.Event()
    second_done = threading.Event()

    def filter_query(_md: MapData, query: str) -> ObjectFilterResult:
        if query == "old":
            first_started.set()
            assert release_first.wait(2)
            return _result("old")
        second_done.set()
        return _result("new")

    monkeypatch.setattr(filter_runner, "filter_objects_by_query", filter_query)
    runner.search_var.value = "old"
    runner._refresh_list()
    assert first_started.wait(1)

    # When
    runner.search_var.value = "new"
    runner._refresh_list()
    assert second_done.wait(1)
    assert runner.posted.wait(1)
    release_first.set()
    runner.run_scheduled()
    assert runner._shutdown_gui_worker_host(1) == ()

    # Then
    assert [item.summary for item in runner.handled] == [("new",)]
    assert not hasattr(runner, "_object_filter_pending")
