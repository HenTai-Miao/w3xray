"""Background map loading tests."""

import threading
import unittest

from w3xtool.api import MapData
from w3xtool.gui_loader import LoadedMap, load_path_payload, prepare_map_view, switch_map_payload
from w3xtool.load_options import object_only_load_options


class TestGuiLoader(unittest.TestCase):
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
