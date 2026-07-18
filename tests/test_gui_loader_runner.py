"""Background worker lifecycle tests for GUI map loading."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import threading
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image

from w3xtool.api import MapData
from w3xtool.icon_evidence_index import IconEvidenceIndex
from w3xtool.gui_loader import LoadedMap
from w3xtool.gui_loader_runner import BackgroundLoaderMixin
from w3xtool.gui_worker_host import GuiWorkerHostMixin
from w3xtool.gui_worker_registry import GuiWorkerTicket


class _Status:
    def __init__(self) -> None:
        self.text = ""

    def configure(self, *, text: str) -> None:
        self.text = text


class _LoaderRunner(BackgroundLoaderMixin, GuiWorkerHostMixin):
    def __init__(self) -> None:
        self.status = _Status()
        self.scheduled: dict[str, Callable[[], None]] = {}
        self.posted = threading.Event()
        self.cancelled: list[str] = []
        self._next_after = 1
        self._init_gui_worker_host()
        self._init_background_loader()

    def after(self, delay_ms: int, callback: Callable[[], None]) -> str:
        _ = delay_ms
        after_id = f"after-{self._next_after}"
        self._next_after += 1
        self.scheduled[after_id] = callback
        return after_id

    def after_cancel(self, after_id: str) -> None:
        self.cancelled.append(after_id)
        self.scheduled.pop(after_id, None)

    def _post_gui_worker(
        self,
        ticket: GuiWorkerTicket,
        callback: Callable[[], None],
        *,
        cleanup: Callable[[], None] | None = None,
    ) -> bool:
        accepted = super()._post_gui_worker(ticket, callback, cleanup=cleanup)
        if accepted:
            self.posted.set()
        return accepted

    def run_scheduled(self) -> None:
        callbacks = tuple(self.scheduled.values())
        self.scheduled.clear()
        for callback in callbacks:
            callback()


class _Resolver:
    def __init__(self) -> None:
        self.closed = threading.Event()

    def close(self) -> None:
        self.closed.set()

    def get_image(self, path: str) -> Image.Image | None:
        _ = path
        return None

    def build_evidence_index(self, md: MapData) -> IconEvidenceIndex:
        _ = md
        return IconEvidenceIndex.build()


def _loaded_map(resolver: _Resolver, name: str) -> LoadedMap:
    return LoadedMap(
        MapData(path="x.w3x", name=name),
        [],
        [],
        resolver,
        None,
        None,
    )


def test_shutdown_returns_before_blocked_loader_and_discards_late_payload() -> None:
    # Given
    runner = _LoaderRunner()
    resolver = _Resolver()
    started = threading.Event()
    release = threading.Event()
    shutdown_done = threading.Event()

    def build_payload() -> LoadedMap:
        started.set()
        assert release.wait(2)
        return _loaded_map(resolver, "blocked")

    runner._start_loader_job(
        status="busy",
        build_payload=build_payload,
        error_status="failed",
        source_path=None,
    )
    assert started.wait(1)
    closer = threading.Thread(
        target=lambda: (runner._shutdown_background_loader(), shutdown_done.set()),
        daemon=True,
    )

    # When
    closer.start()
    returned_before_release = shutdown_done.wait(0.2)
    release.set()
    assert resolver.closed.wait(1)
    closer.join(1)

    # Then
    assert returned_before_release
    assert not closer.is_alive()
    assert not hasattr(runner, "_load_workers")
    assert runner._shutdown_gui_worker_host(1) == ()


def test_replaced_loader_discards_obsolete_resolver_without_tk_callback() -> None:
    # Given
    runner = _LoaderRunner()
    stale = _Resolver()
    current = _Resolver()
    stale_started = threading.Event()
    release_stale = threading.Event()
    current_built = threading.Event()

    def build_stale() -> LoadedMap:
        stale_started.set()
        assert release_stale.wait(2)
        return _loaded_map(stale, "stale")

    def build_current() -> LoadedMap:
        current_built.set()
        return _loaded_map(current, "current")

    runner._start_loader_job(
        status="old",
        build_payload=build_stale,
        error_status="failed",
        source_path=None,
    )
    assert stale_started.wait(1)

    # When
    runner._start_loader_job(
        status="new",
        build_payload=build_current,
        error_status="failed",
        source_path=None,
    )
    assert current_built.wait(1)
    assert runner.posted.wait(1)
    release_stale.set()
    assert stale.closed.wait(1)

    # Then
    assert len(runner.scheduled) == 1
    with patch.object(runner, "_handle_loader_payload") as handle:
        runner.run_scheduled()
    handle.assert_called_once()
    assert not current.closed.is_set()
    runner._shutdown_background_loader()
    assert runner._shutdown_gui_worker_host(1) == ()


def test_source_open_failure_uses_archive_diagnosis() -> None:
    # Given
    runner = _LoaderRunner()
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "broken.w3x"
        path.write_bytes(b"plain data")
        shown: list[str] = []

        # When
        with patch(
            "w3xtool.gui_loader_runner.messagebox.showerror",
            side_effect=lambda _title, message: shown.append(message),
        ):
            runner._start_loader_job(
                status="busy",
                build_payload=lambda: (_ for _ in ()).throw(
                    ValueError("raw parser error")
                ),
                error_status="解析失败",
                source_path=str(path),
            )
            assert runner.posted.wait(1)
            runner.run_scheduled()

    # Then
    assert len(shown) == 1
    assert "MPQ 头" in shown[0]
    assert "raw parser error" not in shown[0]
    assert runner._shutdown_gui_worker_host(1) == ()


def test_map_switch_failure_keeps_non_archive_error() -> None:
    # Given
    runner = _LoaderRunner()
    shown: list[str] = []

    # When
    with patch(
        "w3xtool.gui_loader_runner.messagebox.showerror",
        side_effect=lambda _title, message: shown.append(message),
    ):
        runner._start_loader_job(
            status="busy",
            build_payload=lambda: (_ for _ in ()).throw(
                ValueError("view preparation failed")
            ),
            error_status="切换失败",
            source_path=None,
        )
        assert runner.posted.wait(1)
        runner.run_scheduled()

    # Then
    assert shown == ["view preparation failed"]
    assert runner._shutdown_gui_worker_host(1) == ()
