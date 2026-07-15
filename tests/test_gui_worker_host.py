"""Tk callback delivery contracts for shared GUI workers."""

from __future__ import annotations

from collections.abc import Callable
import threading
from tkinter import TclError

from w3xtool.gui_worker_host import GuiWorkerHostMixin
from w3xtool.gui_worker_registry import GuiWorkerTicket


class _Host(GuiWorkerHostMixin):
    def __init__(self) -> None:
        self.scheduled: dict[str, Callable[[], None]] = {}
        self.after_threads: list[int] = []
        self._after_next = 1
        self._init_gui_worker_host()

    def after(self, delay_ms: int, callback: Callable[[], None]) -> str:
        assert delay_ms >= 0
        self.after_threads.append(threading.get_ident())
        after_id = f"after-{self._after_next}"
        self._after_next += 1
        self.scheduled[after_id] = callback
        return after_id

    def after_cancel(self, after_id: str) -> None:
        self.scheduled.pop(after_id, None)

    def run_next(self) -> None:
        after_id = next(iter(self.scheduled))
        callback = self.scheduled.pop(after_id)
        callback()


class _ClosedHost(_Host):
    def __init__(self) -> None:
        self.closed = False
        super().__init__()
        self.closed = True

    def after(self, delay_ms: int, callback: Callable[[], None]) -> str:
        if self.closed:
            raise TclError("application destroyed")
        return super().after(delay_ms, callback)


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
    host.run_next()

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
    host.run_next()

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
    queued_callback = next(iter(host.scheduled.values()))

    # When
    lingering = host._shutdown_gui_worker_host(1)

    # Then
    assert lingering == ()
    assert cleaned == ["queued"]
    queued_callback()
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
    assert host.scheduled == {}


def test_worker_never_calls_tk_after_from_its_background_thread() -> None:
    # Given
    host = _Host()
    finished = threading.Event()
    main_thread = threading.get_ident()

    def worker(ticket: GuiWorkerTicket) -> None:
        assert host._post_gui_worker(
            ticket,
            lambda: None,
        )
        finished.set()

    # When
    _ = host._start_gui_worker("export", worker, replace=False)
    assert finished.wait(1)

    # Then
    assert host.after_threads == [main_thread]
    assert host._shutdown_gui_worker_host(1) == ()


def test_poll_reschedule_failure_cleans_result_arriving_after_tk_closes() -> None:
    # Given
    host = _ClosedHost()
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
            cleanup=lambda: cleaned.append("closed"),
        )
        finished.set()

    _ = host._start_gui_worker("export", worker, replace=False)
    assert started.wait(1)

    # When
    host.run_next()
    release.set()
    assert finished.wait(1)

    # Then
    assert cleaned == ["closed"]
    assert host._shutdown_gui_worker_host(1) == ()
