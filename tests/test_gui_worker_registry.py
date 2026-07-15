"""Bounded GUI worker registry lifecycle contracts."""

from __future__ import annotations

import threading
from time import monotonic

import pytest

from w3xtool.gui_worker_registry import (
    GuiWorkerRegistry,
    GuiWorkerRegistryStopped,
    GuiWorkerTicket,
)


def test_shutdown_is_bounded_when_worker_ignores_cancellation() -> None:
    # Given
    registry = GuiWorkerRegistry()
    started = threading.Event()
    release = threading.Event()

    def block(_ticket: GuiWorkerTicket) -> None:
        started.set()
        _ = release.wait(2)

    _ = registry.start("loader", block, replace=False)
    assert started.wait(1)

    # When
    began = monotonic()
    lingering = registry.shutdown(timeout_seconds=0.05)
    elapsed = monotonic() - began
    release.set()

    # Then
    assert elapsed < 0.25
    assert lingering == ("loader",)


def test_replaced_ticket_cannot_deliver_callback() -> None:
    # Given
    registry = GuiWorkerRegistry()
    first_ready = threading.Event()
    second_ready = threading.Event()
    tickets: list[GuiWorkerTicket] = []

    def collect_first(ticket: GuiWorkerTicket) -> None:
        tickets.append(ticket)
        first_ready.set()

    def collect_second(ticket: GuiWorkerTicket) -> None:
        tickets.append(ticket)
        second_ready.set()

    first = registry.start("filter", collect_first, replace=True)
    assert first_ready.wait(1)

    # When
    second = registry.start("filter", collect_second, replace=True)
    assert second_ready.wait(1)

    # Then
    assert tickets == [first, second]
    assert not registry.accepts(first)
    assert registry.accepts(second)
    assert registry.shutdown(timeout_seconds=0) == ()


def test_cancel_group_invalidates_all_group_workers() -> None:
    # Given
    registry = GuiWorkerRegistry()
    release = threading.Event()
    started = threading.Barrier(3)

    def block(_ticket: GuiWorkerTicket) -> None:
        _ = started.wait(timeout=1)
        _ = release.wait(2)

    first = registry.start("export", block, replace=False)
    second = registry.start("export", block, replace=False)
    _ = started.wait(timeout=1)

    # When
    registry.cancel_group("export")

    # Then
    assert first.cancellation.is_set()
    assert second.cancellation.is_set()
    assert not registry.accepts(first)
    assert not registry.accepts(second)
    release.set()


def test_shutdown_uses_one_shared_join_deadline() -> None:
    # Given
    registry = GuiWorkerRegistry()
    release = threading.Event()
    started = threading.Barrier(3)

    def block(_ticket: GuiWorkerTicket) -> None:
        _ = started.wait(timeout=1)
        _ = release.wait(2)

    _ = registry.start("first", block, replace=False)
    _ = registry.start("second", block, replace=False)
    _ = started.wait(timeout=1)

    # When
    began = monotonic()
    lingering = registry.shutdown(timeout_seconds=0.05)
    elapsed = monotonic() - began
    release.set()

    # Then
    assert elapsed < 0.25
    assert lingering == ("first", "second")


def test_shutdown_is_idempotent_and_rejects_new_workers() -> None:
    # Given
    registry = GuiWorkerRegistry()

    # When
    first = registry.shutdown(timeout_seconds=0)
    second = registry.shutdown(timeout_seconds=0)

    # Then
    assert first == ()
    assert second == ()
    with pytest.raises(GuiWorkerRegistryStopped):
        registry.start("late", lambda _ticket: None, replace=False)


def test_finish_is_safe_when_cancellation_wins_worker_race() -> None:
    # Given
    registry = GuiWorkerRegistry()
    started = threading.Event()
    release = threading.Event()

    def finish_late(_ticket: GuiWorkerTicket) -> None:
        started.set()
        _ = release.wait(1)

    ticket = registry.start("scan", finish_late, replace=False)
    assert started.wait(1)

    # When
    registry.cancel_group("scan")
    release.set()

    # Then
    assert ticket.cancellation.is_set()
    assert not registry.accepts(ticket)
    assert registry.shutdown(timeout_seconds=1) == ()
    registry.finish(ticket)
