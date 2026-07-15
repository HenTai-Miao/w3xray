"""Tk callback delivery contracts for shared GUI workers."""

from __future__ import annotations

from collections.abc import Callable
import threading
from tkinter import TclError

from w3xtool.gui_worker_host import GuiWorkerHostMixin
from w3xtool.gui_worker_registry import GuiWorkerTicket


class _Host(GuiWorkerHostMixin):
    def __init__(self) -> None:
        self.scheduled: list[Callable[[], None]] = []
        self._init_gui_worker_host()

    def after(self, delay_ms: int, callback: Callable[[], None]) -> str:
        assert delay_ms == 0
        self.scheduled.append(callback)
        return f"after-{len(self.scheduled)}"


class _ClosedHost(_Host):
    def after(self, delay_ms: int, callback: Callable[[], None]) -> str:
        _ = delay_ms, callback
        raise TclError("application destroyed")


def test_current_ticket_delivers_posted_callback() -> None:
    # Given
    host = _Host()
    posted = threading.Event()
    delivered: list[str] = []
    cleaned: list[str] = []

    def worker(ticket: GuiWorkerTicket) -> None:
        assert host._post_gui_worker(
            ticket,
            lambda: delivered.append("delivered"),
            cleanup=lambda: cleaned.append("cleaned"),
        )
        posted.set()

    _ = host._start_gui_worker("loader", worker, replace=True)
    assert posted.wait(1)

    # When
    host.scheduled.pop()()

    # Then
    assert delivered == ["delivered"]
    assert cleaned == []
    assert host._shutdown_gui_worker_host(1) == ()


def test_replaced_ticket_cleans_callback_at_tk_delivery_boundary() -> None:
    # Given
    host = _Host()
    posted = threading.Event()
    delivered: list[str] = []
    cleaned: list[str] = []

    def worker(ticket: GuiWorkerTicket) -> None:
        assert host._post_gui_worker(
            ticket,
            lambda: delivered.append("stale"),
            cleanup=lambda: cleaned.append("stale"),
        )
        posted.set()

    ticket = host._start_gui_worker("filter", worker, replace=True)
    assert posted.wait(1)
    host._gui_workers.cancel_group("filter")
    assert not host._gui_workers.accepts(ticket)

    # When
    host.scheduled.pop()()

    # Then
    assert delivered == []
    assert cleaned == ["stale"]
    assert host._shutdown_gui_worker_host(1) == ()


def test_shutdown_cleans_callback_already_queued_for_tk() -> None:
    # Given
    host = _Host()
    posted = threading.Event()
    cleaned: list[str] = []

    def worker(ticket: GuiWorkerTicket) -> None:
        assert host._post_gui_worker(
            ticket,
            lambda: None,
            cleanup=lambda: cleaned.append("queued"),
        )
        posted.set()

    _ = host._start_gui_worker("casc", worker, replace=False)
    assert posted.wait(1)

    # When
    lingering = host._shutdown_gui_worker_host(1)

    # Then
    assert lingering == ()
    assert cleaned == ["queued"]
    host.scheduled.pop()()
    assert cleaned == ["queued"]


def test_result_arriving_after_shutdown_is_cleaned_without_tk_post() -> None:
    # Given
    host = _Host()
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    cleaned: list[str] = []

    def worker(ticket: GuiWorkerTicket) -> None:
        started.set()
        _ = release.wait(1)
        assert not host._post_gui_worker(
            ticket,
            lambda: None,
            cleanup=lambda: cleaned.append("late"),
        )
        finished.set()

    _ = host._start_gui_worker("loader", worker, replace=False)
    assert started.wait(1)
    assert host._shutdown_gui_worker_host(0) == ("loader",)

    # When
    release.set()
    assert finished.wait(1)

    # Then
    assert cleaned == ["late"]
    assert host.scheduled == []


def test_tcl_post_failure_cleans_payload_immediately() -> None:
    # Given
    host = _ClosedHost()
    finished = threading.Event()
    cleaned: list[str] = []

    def worker(ticket: GuiWorkerTicket) -> None:
        assert not host._post_gui_worker(
            ticket,
            lambda: None,
            cleanup=lambda: cleaned.append("closed"),
        )
        finished.set()

    # When
    _ = host._start_gui_worker("export", worker, replace=False)
    assert finished.wait(1)

    # Then
    assert cleaned == ["closed"]
    assert host._shutdown_gui_worker_host(1) == ()
