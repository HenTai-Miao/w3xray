"""Background worker lifecycle tests for GUI map loading."""

import queue
import threading
import unittest
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image

from w3xtool.api import MapData
from w3xtool.gui_loader import LoaderError, LoadedMap, LoaderPayload
from w3xtool.gui_loader_runner import BackgroundLoaderMixin

type _WorkerBuilder = Callable[[], LoaderPayload]
type _WorkerTarget = Callable[[int, _WorkerBuilder, str, str | None], None]
type _WorkerArgs = tuple[int, _WorkerBuilder, str, str | None]


class _Status:
    def configure(self, **_values: str) -> None:
        return


class _LoaderRunner(BackgroundLoaderMixin):
    def __init__(self) -> None:
        self.status = _Status()
        self.scheduled: list[Callable[[], None]] = []
        self.cancelled: list[str] = []
        self._init_background_loader()

    def after(self, delay_ms: int, callback: Callable[[], None]) -> str:
        _ = delay_ms
        self.scheduled.append(callback)
        return f"after-{len(self.scheduled)}"

    def after_cancel(self, poll_id: str) -> None:
        self.cancelled.append(poll_id)


class _Resolver:
    def __init__(self) -> None:
        self.closed = threading.Event()

    def close(self) -> None:
        self.closed.set()

    def get_image(self, path: str) -> Image.Image | None:
        _ = path
        return None


class TestGuiLoaderRunner(unittest.TestCase):
    def test_shutdown_drains_already_queued_loaded_map_resolver(self) -> None:
        # Given: a completed result owns a resolver that UI polling has not consumed.
        runner = _LoaderRunner()
        resolver = _Resolver()
        payload = LoadedMap(
            MapData(path="x.w3x", name="queued"),
            [],
            [],
            resolver,
            None,
            None,
        )
        runner._load_results.put((1, payload))

        # When: loader shutdown runs.
        runner._shutdown_background_loader()

        # Then: the queued resolver is closed and the queue is empty.
        self.assertTrue(resolver.closed.is_set())
        self.assertTrue(runner._load_results.empty())

    def test_shutdown_waits_for_blocked_worker_then_discards_payload(self) -> None:
        # Given: a worker is blocked before it can queue a resolver-bearing payload.
        runner = _LoaderRunner()
        resolver = _Resolver()
        worker_started = threading.Event()
        release_worker = threading.Event()
        join_called = threading.Event()
        shutdown_done = threading.Event()
        real_thread = threading.Thread

        class _ObservedThread:
            def __init__(
                self,
                *,
                target: _WorkerTarget,
                args: _WorkerArgs,
                daemon: bool,
                name: str,
            ) -> None:
                self._thread = real_thread(
                    target=target,
                    args=args,
                    daemon=daemon,
                    name=name,
                )

            def start(self) -> None:
                self._thread.start()

            def join(self) -> None:
                join_called.set()
                self._thread.join()

        def build_payload() -> LoadedMap:
            worker_started.set()
            self.assertTrue(release_worker.wait(2))
            return LoadedMap(
                MapData(path="x.w3x", name="blocked"),
                [],
                [],
                resolver,
                None,
                None,
            )

        def shutdown() -> None:
            runner._shutdown_background_loader()
            shutdown_done.set()

        with patch("w3xtool.gui_loader_runner.threading.Thread", _ObservedThread):
            runner._start_loader_job(
                status="busy",
                build_payload=build_payload,
                error_status="failed",
                source_path=None,
            )
            self.assertTrue(worker_started.wait(2))
            closer = real_thread(target=shutdown, daemon=True)
            closer.start()
            self.assertTrue(join_called.wait(2))
            self.assertFalse(shutdown_done.is_set())
            release_worker.set()
            self.assertTrue(shutdown_done.wait(2))
            closer.join()

        # Then: shutdown returns only after discarding the worker payload.
        self.assertTrue(resolver.closed.is_set())
        self.assertTrue(runner._load_results.empty())
        self.assertEqual(runner._load_workers, {})

    def test_poll_reaps_worker_for_completed_stale_result(self) -> None:
        # Given: a completed worker has queued a result from an obsolete token.
        runner = _LoaderRunner()
        joined: list[bool] = []

        class _CompletedThread:
            def join(self) -> None:
                joined.append(True)

        runner._load_token = 2
        runner._load_pending.add(1)
        runner._load_workers[1] = _CompletedThread()
        runner._load_results.put((1, LoaderError("old", "old", "old")))

        # When: normal polling discards that stale result.
        runner._poll_loader_results()

        # Then: the completed thread handle is reaped with its result.
        self.assertEqual(joined, [True])
        self.assertEqual(runner._load_workers, {})

    def test_source_open_failure_uses_archive_diagnosis(self) -> None:
        # Given: a real selected source with no MPQ header and a failing loader.
        runner = object.__new__(BackgroundLoaderMixin)
        runner._load_results = queue.Queue()
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.w3x"
            path.write_bytes(b"plain data")

            # When: the source-path loader boundary catches the failure.
            runner._run_loader_job(
                1,
                lambda: (_ for _ in ()).throw(ValueError("raw parser error")),
                "解析失败",
                str(path),
            )
            _token, payload = runner._load_results.get_nowait()

        # Then: GUI text is the unified archive diagnosis, not a raw parser error.
        assert isinstance(payload, LoaderError)
        self.assertIn("MPQ 头", payload.message)
        self.assertNotIn("raw parser error", payload.message)

    def test_map_switch_failure_keeps_non_archive_error(self) -> None:
        # Given: an already-open map switch that fails during view preparation.
        runner = object.__new__(BackgroundLoaderMixin)
        runner._load_results = queue.Queue()

        # When: the worker catches the non-source failure.
        runner._run_loader_job(
            2,
            lambda: (_ for _ in ()).throw(ValueError("view preparation failed")),
            "切换失败",
            None,
        )
        _token, payload = runner._load_results.get_nowait()

        # Then: it is not disguised as an archive-open diagnosis.
        assert isinstance(payload, LoaderError)
        self.assertEqual(payload.message, "view preparation failed")


if __name__ == "__main__":
    unittest.main()
