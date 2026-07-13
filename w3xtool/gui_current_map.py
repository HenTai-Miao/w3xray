"""Tk-safe current Warcraft map acquisition."""

from __future__ import annotations

import queue
import threading
from tkinter import TclError, messagebox
from typing import Final, assert_never

from .current_map_discovery import locate_current_map
from .current_map_models import CurrentMapResolution
from .gui_current_map_presenter import (
    AcceptedSuggestion,
    CurrentMapEvent,
    ResolutionReady,
    SnapshotReady,
    TerminalStatus,
    WORKER_ERROR_MESSAGE,
    WORKER_ERROR_TITLE,
    WorkerError,
    present_resolution,
)
from .gui_current_map_worker import (
    CurrentMapHost,
    collect_extra_roots,
    discard_event,
    run_discovery,
    run_snapshot,
)
from .current_map_snapshot import (
    CurrentMapSnapshot,
    cleanup_current_map_snapshot,
    cleanup_stale_current_map_snapshots,
    create_current_map_snapshot,
)


_POLL_MS: Final = 35


class CurrentMapGuiMixin(CurrentMapHost):
    """Own the GUI entry point for current-map acquisition."""

    def _init_current_map_gui(self) -> None:
        if getattr(self, "_current_map_initialized", False):
            return
        self._current_map_initialized = True
        self._current_map_results: queue.Queue[tuple[int, CurrentMapEvent]] = (
            queue.Queue()
        )
        self._current_map_lock = threading.Lock()
        self._current_map_generation = 0
        self._current_map_pending = False
        self._current_map_stopped = False
        self._current_map_poll_id: str | None = None
        self._current_map_snapshots: list[CurrentMapSnapshot] = []
        cleanup_stale_current_map_snapshots()

    def on_open_current_map(self) -> None:
        """Start acquiring the current Warcraft map."""
        with self._current_map_lock:
            if self._current_map_stopped or self._current_map_pending:
                return
            self._current_map_generation += 1
            generation = self._current_map_generation
            self._current_map_pending = True
        roots = collect_extra_roots(self._cur_dir, self._load_config())
        self.current_map_button.configure(state="disabled")
        self.status.configure(text="正在获取当前地图 …")
        worker = threading.Thread(
            target=run_discovery,
            args=(
                generation,
                roots,
                locate_current_map,
                create_current_map_snapshot,
                self._put_current_map_event,
                self._put_current_map_snapshot,
            ),
            daemon=True,
            name=f"w3xray-current-map-{generation}",
        )
        worker.start()
        self._schedule_current_map_poll()

    def _shutdown_current_map_gui(self) -> None:
        """Stop acquisition and release every snapshot owned by this session."""
        with self._current_map_lock:
            if self._current_map_stopped:
                return
            self._current_map_stopped = True
            self._current_map_generation += 1
            self._current_map_pending = False
            snapshots = tuple(self._current_map_snapshots)
            self._current_map_snapshots.clear()
        poll_id = self._current_map_poll_id
        self._current_map_poll_id = None
        if poll_id is not None:
            try:
                self.after_cancel(poll_id)
            except TclError:
                self._current_map_poll_id = None
        for snapshot in snapshots:
            cleanup_current_map_snapshot(snapshot)

    def _put_current_map_event(
        self, generation: int, event: ResolutionReady | WorkerError
    ) -> None:
        if self._current_map_is_active(generation):
            self._current_map_results.put((generation, event))

    def _current_map_is_active(self, generation: int) -> bool:
        with self._current_map_lock:
            return (
                not self._current_map_stopped
                and generation == self._current_map_generation
            )

    def _adopt_current_map_snapshot(
        self,
        generation: int,
        snapshot: CurrentMapSnapshot,
    ) -> bool:
        with self._current_map_lock:
            active = (
                not self._current_map_stopped
                and generation == self._current_map_generation
            )
            if active:
                self._current_map_snapshots.append(snapshot)
        return active

    def _schedule_current_map_poll(self) -> None:
        if self._current_map_poll_id is None:
            self._current_map_poll_id = self.after(
                _POLL_MS, self._poll_current_map_results
            )

    def _poll_current_map_results(self) -> None:
        self._current_map_poll_id = None
        while True:
            try:
                generation, event = self._current_map_results.get_nowait()
            except queue.Empty:
                break
            if not self._current_map_is_active(generation):
                discard_event(
                    event,
                    self._current_map_lock,
                    self._current_map_snapshots,
                    cleanup_current_map_snapshot,
                )
                continue
            match event:
                case SnapshotReady(snapshot=snapshot):
                    self._start_path_load(str(snapshot.path))
                    self._finish_current_map_request(generation)
                case ResolutionReady(resolution=resolution):
                    self._handle_current_map_resolution(generation, resolution)
                case WorkerError():
                    messagebox.showerror(WORKER_ERROR_TITLE, WORKER_ERROR_MESSAGE)
                    self._finish_current_map_request(generation, WORKER_ERROR_TITLE)
                case unreachable:
                    assert_never(unreachable)
        with self._current_map_lock:
            pending = self._current_map_pending and not self._current_map_stopped
        if pending:
            self._schedule_current_map_poll()

    def _handle_current_map_resolution(
        self, generation: int, resolution: CurrentMapResolution
    ) -> None:
        outcome = present_resolution(resolution)
        match outcome:
            case TerminalStatus(text=status):
                self._finish_current_map_request(generation, status)
                return
            case AcceptedSuggestion(path=path):
                pass
            case unreachable:
                assert_never(unreachable)
        worker = threading.Thread(
            target=run_snapshot,
            args=(
                generation,
                path,
                create_current_map_snapshot,
                self._put_current_map_event,
                self._put_current_map_snapshot,
            ),
            daemon=True,
            name=f"w3xray-current-map-snapshot-{generation}",
        )
        worker.start()

    def _put_current_map_snapshot(
        self,
        generation: int,
        snapshot: CurrentMapSnapshot,
    ) -> None:
        if self._adopt_current_map_snapshot(generation, snapshot):
            self._current_map_results.put((generation, SnapshotReady(snapshot)))
        else:
            cleanup_current_map_snapshot(snapshot)

    def _finish_current_map_request(
        self,
        generation: int,
        terminal_status: str | None = None,
    ) -> None:
        with self._current_map_lock:
            if generation != self._current_map_generation:
                return
            self._current_map_pending = False
        self.current_map_button.configure(state="normal")
        if terminal_status is not None:
            self.status.configure(text=terminal_status)
