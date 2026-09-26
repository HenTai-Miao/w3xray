"""Tk-safe Warcraft companion-mode watching and auto-load wiring."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
import threading
from typing import TYPE_CHECKING, Final, assert_never

from .companion_watch import run_companion_watch, source_key
from .current_map_discovery import locate_current_map
from .current_map_models import CurrentMapResolution
from .current_map_process import ProcessProbeReport, probe_game_processes
from .current_map_snapshot import (
    CurrentMapSnapshot,
    cleanup_current_map_snapshot,
    create_current_map_snapshot,
)
from .gui_current_map_presenter import (
    AcceptedSuggestion,
    TerminalStatus,
    present_resolution,
)
from .gui_current_map_worker import collect_extra_roots
from .gui_worker_registry import GuiWorkerRegistryStopped

_COMPANION_GROUP: Final = "companion"
_COMPANION_LOAD_GROUP: Final = "companion-load"
_COMPANION_POLL_SECONDS: Final = 5.0
_COMPANION_ENABLED_KEY: Final = "companion_enabled"
_COMPANION_ON_LABEL: Final = "魔兽联动：开"
_COMPANION_OFF_LABEL: Final = "魔兽联动：关"
_COMPANION_LOAD_FAILED_NOTE: Final = "联动创建当前地图快照失败，稍后重试 …"
_ITEM_RELATIONS_TAB: Final = "掉落/获取"


def _locate_with_probe(
    roots: tuple[Path, ...],
    report: ProcessProbeReport,
) -> CurrentMapResolution:
    """Reuse the watch loop's own process probe for one discovery pass."""
    return locate_current_map(roots, process_provider=lambda: report)


if TYPE_CHECKING:
    from typing import Protocol

    from .gui_worker_registry import GuiWorkerTarget, GuiWorkerTicket

    class _Configurable(Protocol):
        def configure(self, **values: str) -> None: ...

        def cget(self, key: str) -> str: ...

    class _TabView(Protocol):
        def set(self, name: str) -> None: ...

    class _TypingConfigurable:
        def configure(self, **values: str) -> None:
            return

        def cget(self, key: str) -> str:
            return key

    class _TypingTabView:
        def set(self, name: str) -> None:
            return

    class CompanionGuiHost:
        """GUI surface the companion mixin relies on."""

        _companion_initialized: bool = False
        _companion_lock: threading.Lock = threading.Lock()
        _companion_stopped: bool = False
        _companion_watch_started: bool = False
        _companion_enabled: bool = False
        _companion_loaded_source: str | None = None
        _companion_snapshot: CurrentMapSnapshot | None = None
        _companion_note: str | None = None
        _current_map_lock: threading.Lock = threading.Lock()
        _current_map_pending: bool = False
        _current_map_snapshots: list[CurrentMapSnapshot] = []
        _cur_dir: Mapping[str, str | Path | None] = {}
        companion_button: _Configurable = _TypingConfigurable()
        status: _Configurable = _TypingConfigurable()
        tabs: _TabView = _TypingTabView()

        def _load_config(self) -> Mapping[str, str | Path | None]: ...

        def _save_config(self, **values: object) -> None: ...

        def _start_path_load(self, path: str) -> None: ...

        def _start_gui_worker(
            self,
            group: str,
            target: GuiWorkerTarget,
            *,
            replace: bool,
        ) -> GuiWorkerTicket: ...

        def _cancel_gui_worker_group(self, group: str) -> None: ...

        def _post_gui_worker(
            self,
            ticket: GuiWorkerTicket,
            callback: Callable[[], None],
            *,
            cleanup: Callable[[], None] | None = None,
        ) -> bool: ...

        def _companion_loaded_source_key(self) -> str | None: ...

        def _on_companion_game_started(self) -> None: ...

        def _on_companion_game_exited(self) -> None: ...

        def _on_companion_map_ready(self, snapshot: CurrentMapSnapshot) -> None: ...

        def _on_companion_map_unresolved(
            self, resolution: CurrentMapResolution
        ) -> None: ...

        def _on_companion_note(self, message: str) -> None: ...
else:
    CompanionGuiHost = object


class _PostedCompanionHooks:
    """Marshal watch-loop events onto the Tk thread or reclaim their payloads."""

    def __init__(self, host: CompanionGuiHost, ticket: GuiWorkerTicket) -> None:
        self._host = host
        self._ticket = ticket

    def on_game_started(self) -> None:
        _ = self._host._post_gui_worker(
            self._ticket,
            self._host._on_companion_game_started,
        )

    def on_game_exited(self) -> None:
        _ = self._host._post_gui_worker(
            self._ticket,
            self._host._on_companion_game_exited,
        )

    def on_map_ready(self, snapshot: CurrentMapSnapshot) -> None:
        _ = self._host._post_gui_worker(
            self._ticket,
            lambda: self._host._on_companion_map_ready(snapshot),
            cleanup=lambda: cleanup_current_map_snapshot(snapshot),
        )

    def on_map_unresolved(self, resolution: CurrentMapResolution) -> None:
        _ = self._host._post_gui_worker(
            self._ticket,
            lambda: self._host._on_companion_map_unresolved(resolution),
        )

    def on_watch_note(self, message: str) -> None:
        _ = self._host._post_gui_worker(
            self._ticket,
            lambda: self._host._on_companion_note(message),
        )


class CompanionGuiMixin(CompanionGuiHost):
    """Toggle and run the Warcraft companion watcher from the GUI."""

    def _init_companion(self) -> None:
        if getattr(self, "_companion_initialized", False):
            return
        self._companion_initialized = True
        self._companion_lock = threading.Lock()
        self._companion_stopped = False
        self._companion_watch_started = False
        self._companion_enabled = bool(self._load_config().get(_COMPANION_ENABLED_KEY))
        self._companion_loaded_source: str | None = None
        self._companion_snapshot: CurrentMapSnapshot | None = None
        self._companion_note: str | None = None

    def _companion_button_label(self) -> str:
        return _COMPANION_ON_LABEL if self._companion_enabled else _COMPANION_OFF_LABEL

    def on_toggle_companion(self) -> None:
        """Enable or disable watching the live Warcraft session."""
        with self._companion_lock:
            if self._companion_stopped:
                return
            self._companion_enabled = not self._companion_enabled
            enabled = self._companion_enabled
        self._save_config(companion_enabled=enabled)
        self.companion_button.configure(text=self._companion_button_label())
        if enabled:
            self._start_companion_watch()
            self.status.configure(text="魔兽联动已开启：等待魔兽启动 …")
        else:
            self._cancel_gui_worker_group(_COMPANION_GROUP)
            with self._companion_lock:
                self._companion_watch_started = False
            self.status.configure(text="魔兽联动已关闭")

    def _start_companion_watch_if_enabled(self) -> None:
        with self._companion_lock:
            enabled = self._companion_enabled and not self._companion_stopped
        if enabled:
            self._start_companion_watch()

    def _start_companion_watch(self) -> None:
        with self._companion_lock:
            if self._companion_stopped or self._companion_watch_started:
                return
            self._companion_watch_started = True
        try:
            _ = self._start_gui_worker(
                _COMPANION_GROUP,
                self._run_companion_watch_target,
                replace=False,
            )
        except GuiWorkerRegistryStopped:
            with self._companion_lock:
                self._companion_watch_started = False

    def _run_companion_watch_target(self, ticket: GuiWorkerTicket) -> None:
        run_companion_watch(
            ticket.cancellation,
            roots_provider=lambda: collect_extra_roots(
                self._cur_dir, self._load_config()
            ),
            probe=probe_game_processes,
            locate=_locate_with_probe,
            snapshot_factory=create_current_map_snapshot,
            loaded_source=self._companion_loaded_source_key,
            hooks=_PostedCompanionHooks(self, ticket),
            interval_seconds=_COMPANION_POLL_SECONDS,
            sleep=ticket.cancellation.wait,
        )

    def _companion_loaded_source_key(self) -> str | None:
        with self._companion_lock:
            loaded = self._companion_loaded_source
        if loaded is not None:
            return loaded
        with self._current_map_lock:
            snapshots = tuple(self._current_map_snapshots)
        if snapshots:
            return source_key(snapshots[-1].source_path)
        return None

    def _on_companion_map_unresolved(self, resolution: CurrentMapResolution) -> None:
        with self._companion_lock:
            if self._companion_stopped:
                return
        with self._current_map_lock:
            pending = self._current_map_pending
        if pending:
            return
        outcome = present_resolution(resolution)
        match outcome:
            case AcceptedSuggestion(path=path):
                self._start_companion_load(path)
            case TerminalStatus(text=text):
                self.status.configure(text=text)
            case unreachable:
                assert_never(unreachable)

    def _start_companion_load(self, path: Path) -> None:
        try:
            _ = self._start_gui_worker(
                _COMPANION_LOAD_GROUP,
                lambda ticket: self._run_companion_load_target(ticket, path),
                replace=True,
            )
        except GuiWorkerRegistryStopped:
            return

    def _run_companion_load_target(self, ticket: GuiWorkerTicket, path: Path) -> None:
        try:
            snapshot = create_current_map_snapshot(path)
        except OSError:
            self._post_gui_worker(
                ticket,
                lambda: self._on_companion_note(_COMPANION_LOAD_FAILED_NOTE),
            )
            return
        _ = self._post_gui_worker(
            ticket,
            lambda: self._on_companion_map_ready(snapshot),
            cleanup=lambda: cleanup_current_map_snapshot(snapshot),
        )

    def _on_companion_game_started(self) -> None:
        with self._companion_lock:
            if self._companion_stopped:
                return
            self._companion_note = None
        self.status.configure(text="检测到魔兽进程，正在定位当前地图 …")

    def _on_companion_game_exited(self) -> None:
        with self._companion_lock:
            if self._companion_stopped:
                return
            self._companion_loaded_source = None
            self._companion_note = None
        self._retire_companion_snapshot()
        self.status.configure(text="魔兽已退出，联动待命 …")

    def _on_companion_map_ready(self, snapshot: CurrentMapSnapshot) -> None:
        with self._companion_lock:
            if self._companion_stopped:
                cleanup_current_map_snapshot(snapshot)
                return
            previous = self._companion_snapshot
            self._companion_snapshot = snapshot
            self._companion_loaded_source = source_key(snapshot.source_path)
            self._companion_note = None
        if previous is not None:
            cleanup_current_map_snapshot(previous)
        self.status.configure(text=f"联动加载当前地图：{snapshot.source_path.name}")
        self._start_path_load(str(snapshot.path))
        self.tabs.set(_ITEM_RELATIONS_TAB)

    def _on_companion_note(self, message: str) -> None:
        with self._companion_lock:
            if self._companion_stopped or self._companion_note == message:
                return
            self._companion_note = message
        self.status.configure(text=message)

    def _retire_companion_snapshot(self) -> None:
        with self._companion_lock:
            snapshot = self._companion_snapshot
            self._companion_snapshot = None
        if snapshot is not None:
            cleanup_current_map_snapshot(snapshot)

    def _shutdown_companion(self) -> None:
        """Stop the watcher and release every companion-owned snapshot."""
        with self._companion_lock:
            if self._companion_stopped:
                return
            self._companion_stopped = True
        self._cancel_gui_worker_group(_COMPANION_GROUP)
        self._cancel_gui_worker_group(_COMPANION_LOAD_GROUP)
        self._retire_companion_snapshot()


__all__ = ("CompanionGuiMixin",)
