"""Tk-safe host helpers backed by the shared GUI worker registry."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import threading
from tkinter import TclError
from typing import TYPE_CHECKING

from .gui_worker_registry import (
    GuiWorkerRegistry,
    GuiWorkerTarget,
    GuiWorkerTicket,
)

if TYPE_CHECKING:

    class _TkAfterHost:
        _gui_workers: GuiWorkerRegistry = GuiWorkerRegistry()
        _gui_post_lock: threading.Lock = threading.Lock()
        _gui_post_next: int = 0
        _gui_posts: dict[int, _PendingGuiPost] = {}

        def after(self, delay_ms: int, callback: Callable[[], None]) -> str: ...

else:
    _TkAfterHost = object


@dataclass(frozen=True, slots=True)
class _PendingGuiPost:
    ticket: GuiWorkerTicket
    callback: Callable[[], None]
    cleanup: Callable[[], None] | None


class GuiWorkerHostMixin(_TkAfterHost):
    """Expose one worker registry to all GUI feature mixins."""

    def _init_gui_worker_host(self) -> None:
        self._gui_workers = GuiWorkerRegistry()
        self._gui_post_lock = threading.Lock()
        self._gui_post_next = 1
        self._gui_posts = {}

    def _start_gui_worker(
        self,
        group: str,
        target: GuiWorkerTarget,
        *,
        replace: bool,
    ) -> GuiWorkerTicket:
        return self._gui_workers.start(group, target, replace=replace)

    def _post_gui_worker(
        self,
        ticket: GuiWorkerTicket,
        callback: Callable[[], None],
        *,
        cleanup: Callable[[], None] | None = None,
    ) -> bool:
        """Queue one guarded Tk callback or reclaim its stale payload."""
        if not self._gui_workers.accepts(ticket):
            _run_cleanup(cleanup)
            return False
        with self._gui_post_lock:
            if not self._gui_workers.accepts(ticket):
                post_id = 0
            else:
                post_id = self._gui_post_next
                self._gui_post_next += 1
                self._gui_posts[post_id] = _PendingGuiPost(
                    ticket,
                    callback,
                    cleanup,
                )
        if post_id == 0:
            _run_cleanup(cleanup)
            return False
        try:
            _ = self.after(0, lambda: self._deliver_gui_post(post_id))
        except TclError:
            pending = self._take_gui_post(post_id)
            if pending is not None:
                _run_cleanup(pending.cleanup)
            return False
        return True

    def _shutdown_gui_worker_host(self, timeout_seconds: float) -> tuple[str, ...]:
        """Stop workers and reclaim callbacks Tk will never deliver."""
        lingering = self._gui_workers.shutdown(timeout_seconds)
        self._cleanup_gui_posts(None)
        return lingering

    def _cancel_gui_worker_group(self, group: str) -> None:
        """Invalidate one subsystem and reclaim its queued Tk payloads."""
        self._gui_workers.cancel_group(group)
        self._cleanup_gui_posts(group)

    def _deliver_gui_post(self, post_id: int) -> None:
        pending = self._take_gui_post(post_id)
        if pending is None:
            return
        if self._gui_workers.accepts(pending.ticket):
            pending.callback()
            return
        _run_cleanup(pending.cleanup)

    def _take_gui_post(self, post_id: int) -> _PendingGuiPost | None:
        with self._gui_post_lock:
            return self._gui_posts.pop(post_id, None)

    def _cleanup_gui_posts(self, group: str | None) -> None:
        with self._gui_post_lock:
            post_ids = tuple(
                post_id
                for post_id, post in self._gui_posts.items()
                if group is None or post.ticket.group == group
            )
            pending = tuple(self._gui_posts.pop(post_id) for post_id in post_ids)
        for post in pending:
            _run_cleanup(post.cleanup)


def _run_cleanup(cleanup: Callable[[], None] | None) -> None:
    if cleanup is not None:
        cleanup()


__all__ = ("GuiWorkerHostMixin",)
