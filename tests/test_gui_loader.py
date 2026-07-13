"""Background map loading tests."""

import threading
import unittest
from pathlib import Path
import queue
from tempfile import TemporaryDirectory
from unittest.mock import patch

from w3xtool.api import MapData
from w3xtool.gui_loader import LoaderError, LoadedMap, load_path_payload, prepare_map_view, switch_map_payload
from w3xtool.gui_loader_runner import BackgroundLoaderMixin
from w3xtool.load_options import object_only_load_options


class _Status:
    def configure(self, **_values) -> None:
        return


class _LoaderRunner(BackgroundLoaderMixin):
    def __init__(self) -> None:
        self.status = _Status()
        self.scheduled = []
        self.cancelled = []
        self._init_background_loader()

    def after(self, _delay_ms, callback):
        self.scheduled.append(callback)
        return f"after-{len(self.scheduled)}"

    def after_cancel(self, poll_id) -> None:
        self.cancelled.append(poll_id)


class _Resolver:
    def __init__(self) -> None:
        self.closed = threading.Event()

    def close(self) -> None:
        self.closed.set()


class TestGuiLoader(unittest.TestCase):
    def test_shutdown_drains_already_queued_loaded_map_resolver(self):
        # Given: a completed result owns a resolver that UI polling has not consumed.
        runner = _LoaderRunner()
        resolver = _Resolver()
        payload = LoadedMap(MapData(path="x.w3x", name="queued"), [], [], resolver, None, None)
        runner._load_results.put((1, payload))

        # When: loader shutdown runs.
        runner._shutdown_background_loader()

        # Then: the queued resolver is closed and the queue is empty.
        self.assertTrue(resolver.closed.is_set())
        self.assertTrue(runner._load_results.empty())

    def test_shutdown_waits_for_blocked_worker_then_discards_payload(self):
        # Given: a worker is blocked before it can queue a resolver-bearing payload.
        runner = _LoaderRunner()
        resolver = _Resolver()
        worker_started = threading.Event()
        release_worker = threading.Event()
        join_called = threading.Event()
        shutdown_done = threading.Event()
        real_thread = threading.Thread

        class _ObservedThread:
            def __init__(self, *, target, args, daemon: bool, name: str) -> None:
                self._thread = real_thread(target=target, args=args, daemon=daemon, name=name)

            def start(self) -> None:
                self._thread.start()

            def join(self) -> None:
                join_called.set()
                self._thread.join()

            def is_alive(self) -> bool:
                return self._thread.is_alive()

        def build_payload() -> LoadedMap:
            worker_started.set()
            self.assertTrue(release_worker.wait(2))
            return LoadedMap(MapData(path="x.w3x", name="blocked"), [], [], resolver, None, None)

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

    def test_poll_reaps_worker_for_completed_stale_result(self):
        # Given: a completed worker has queued a result from an obsolete token.
        runner = _LoaderRunner()
        joined = []

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

    def test_source_open_failure_uses_archive_diagnosis(self):
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
        self.assertIsInstance(payload, LoaderError)
        self.assertIn("MPQ 头", payload.message)
        self.assertNotIn("raw parser error", payload.message)

    def test_map_switch_failure_keeps_non_archive_error(self):
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
        self.assertIsInstance(payload, LoaderError)
        self.assertEqual(payload.message, "view preparation failed")

    def test_load_path_payload_prepares_first_campaign_view(self):
        # Given: opening a campaign returns shared data plus one sub-map.
        top = MapData(path="campaign.w3n", name="战役共享")
        sub = MapData(path="chapter.w3x", name="第一章")
        top.sub_maps = [sub]
        calls = []

        def load(path: str) -> MapData:
            self.assertEqual(path, "campaign.w3n")
            return top

        def prepare(active, campaign_path, views, *, load_options):
            calls.append((active, campaign_path, views))
            return LoadedMap(active, [], [], None, views, campaign_path)

        # When: the path payload is built.
        result = load_path_payload("campaign.w3n", load=load, prepare=prepare)

        # Then: the visible map is the shared campaign view, with child views preserved.
        self.assertIs(result.active, top)
        self.assertEqual(result.campaign_path, "campaign.w3n")
        self.assertEqual(calls[0][1], "campaign.w3n")
        self.assertEqual(calls[0][2][1], ("第一章", sub))

    def test_switch_map_payload_keeps_campaign_icon_context(self):
        # Given: a loaded campaign sub-map and its parent archive path.
        sub = MapData(path="chapter.w3x", name="第一章")
        calls = []

        def prepare(active, campaign_path, views, *, load_options):
            calls.append((active, campaign_path, views))
            return LoadedMap(active, [], [], None, views, campaign_path)

        # When: switching to that sub-map.
        result = switch_map_payload(sub, "campaign.w3n", prepare=prepare)

        # Then: preparation keeps the campaign path for shared icon lookup.
        self.assertIs(result.active, sub)
        self.assertEqual(result.campaign_path, "campaign.w3n")
        self.assertIsNone(result.views)
        self.assertEqual(calls, [(sub, "campaign.w3n", None)])

    def test_load_path_payload_default_prepare_accepts_load_options(self):
        # Given: the GUI opens a normal map through the default preparation path.
        md = MapData(path="x.w3x", name="普通地图")

        # When: load options are supplied by the settings tab.
        result = load_path_payload(
            "x.w3x",
            load=lambda _path: md,
            load_options=object_only_load_options(),
        )

        # Then: opening reaches preparation instead of failing on call signature.
        self.assertIs(result.active, md)
        self.assertEqual(result.commands, [])
        self.assertEqual(result.recipes, [])

    def test_switch_map_payload_default_prepare_accepts_load_options(self):
        # Given: the GUI switches to an already-loaded campaign child map.
        md = MapData(path="chapter.w3x", name="第一章")

        # When: load options are supplied by the settings tab.
        result = switch_map_payload(
            md,
            "campaign.w3n",
            load_options=object_only_load_options(),
        )

        # Then: switching reaches preparation instead of failing on call signature.
        self.assertIs(result.active, md)
        self.assertEqual(result.campaign_path, "campaign.w3n")

    def test_prepare_map_view_runs_independent_work_in_parallel(self):
        # Given: command, recipe, and icon preparation all block until three workers exist.
        md = MapData(path="x.w3x", name="并行测试图")
        barrier = threading.Barrier(3)
        lock = threading.Lock()
        worker_names = []

        def mark(label):
            with lock:
                worker_names.append((label, threading.current_thread().name))
            barrier.wait(timeout=2)

        def commands(map_data):
            self.assertIs(map_data, md)
            mark("commands")
            return ["cmd"]

        def recipes(map_data):
            self.assertIs(map_data, md)
            mark("recipes")
            return ["recipe"]

        def resolver(map_data, campaign_path):
            self.assertIs(map_data, md)
            self.assertIsNone(campaign_path)
            mark("resolver")
            return "resolver"

        # When: preparation runs.
        result = prepare_map_view(
            md,
            command_loader=commands,
            recipe_loader=recipes,
            resolver_loader=resolver,
        )

        # Then: all independent stages completed on separate preparation workers.
        self.assertEqual(result.commands, ["cmd"])
        self.assertEqual(result.recipes, ["recipe"])
        self.assertEqual(result.resolver, "resolver")
        self.assertEqual({label for label, _ in worker_names}, {"commands", "recipes", "resolver"})
        self.assertGreaterEqual(len({name for _, name in worker_names}), 3)

    def test_prepare_map_view_skips_disabled_modules(self):
        # Given: only object browsing is enabled, so scripts and recipes should not scan.
        md = MapData(path="x.w3x", name="按需加载测试图")
        calls = []

        def commands(_map_data):
            calls.append("commands")
            return ["cmd"]

        def recipes(_map_data):
            calls.append("recipes")
            return ["recipe"]

        def resolver(_map_data, _campaign_path):
            calls.append("resolver")
            return "resolver"

        # When: preparation runs with an object-only profile.
        result = prepare_map_view(
            md,
            load_options=object_only_load_options(),
            command_loader=commands,
            recipe_loader=recipes,
            resolver_loader=resolver,
        )

        # Then: only the object detail icon resolver is prepared.
        self.assertEqual(result.commands, [])
        self.assertEqual(result.recipes, [])
        self.assertEqual(result.resolver, "resolver")
        self.assertEqual(calls, ["resolver"])


if __name__ == "__main__":
    unittest.main()
