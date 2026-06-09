"""GUI 两级导航测试：
- 对战图：左侧扁平地图列表（文件夹里的 .w3x/.w3m）
- 战役图：左侧树形——目录里的 .w3n 为父节点，展开显示其子地图(★共享+各关卡)
"""
import unittest

from w3xtool.api import MapData
from w3xtool.gui import App


class TestModeAndLeftList(unittest.TestCase):
    def setUp(self):
        self.app = App()

    def tearDown(self):
        self.app.destroy()

    def _roots(self):
        return self.app.map_list.get_children()

    def _label(self, iid):
        return self.app.map_list.item(iid, "text").strip()

    # ---- 对战图：扁平 ----
    def test_battle_mode_shows_directory_maps(self):
        self.app._dir_maps = [("p1.w3x", "地图甲"), ("p2.w3x", "地图乙")]
        self.app._on_mode_change("对战图")
        self.assertEqual(self.app.mode, "battle")
        self.assertEqual([self._label(i) for i in self._roots()], ["地图甲", "地图乙"])

    # ---- 战役图：树形 ----
    def test_campaign_tree_lists_campaigns_as_roots(self):
        self.app.mode = "campaign"
        self.app._dir_campaigns = [
            {"path": "a.w3n", "name": "战役A", "loaded": False, "views": None},
            {"path": "b.w3n", "name": "战役B", "loaded": False, "views": None}]
        self.app._populate_left()
        self.assertEqual([self._label(i) for i in self._roots()], ["战役A", "战役B"])

    def test_loaded_campaign_node_has_submap_children(self):
        top = MapData(path="a.w3n", name="战役A")
        s1 = MapData(path="x.w3x", name="XSHZ-1")
        views = [("★共享", top), ("XSHZ-1", s1)]
        self.app.mode = "campaign"
        self.app._dir_campaigns = [{"path": "a.w3n", "name": "战役A",
                                    "loaded": True, "views": views}]
        self.app._populate_left()
        root = self._roots()[0]
        children = self.app.map_list.get_children(root)
        self.assertEqual([self._label(c) for c in children], ["★共享", "XSHZ-1"])
        # 选中子地图节点应能映射回对应 MapData
        sub_iid = children[1]
        self.assertEqual(self.app._node_map[sub_iid], ("md", s1))

    def test_single_open_campaign_shows_expanded(self):
        top = MapData(path="a.w3n", name="战役A")
        s1 = MapData(path="x.w3x", name="XSHZ-1")
        self.app._set_campaign_views([("★共享", top), ("XSHZ-1", s1)], "a.w3n")
        self.assertEqual(self.app.mode, "campaign")
        roots = self._roots()
        self.assertEqual(len(roots), 1)
        children = self.app.map_list.get_children(roots[0])
        self.assertEqual([self._label(c) for c in children], ["★共享", "XSHZ-1"])

    def test_picking_battle_dir_keeps_campaign_list(self):
        self.app._dir_campaigns = [{"path": "a.w3n", "name": "战役A",
                                    "loaded": False, "views": None}]
        self.app._fill_battle([("p.w3x", "地图甲")])
        self.assertEqual(len(self.app._dir_campaigns), 1)   # 战役列表没被清
        self.assertEqual(self.app._dir_maps, [("p.w3x", "地图甲")])

    def test_picking_campaign_dir_keeps_battle_list(self):
        self.app._dir_maps = [("p.w3x", "地图甲")]
        self.app._fill_campaign([{"path": "a.w3n", "name": "战役A",
                                  "loaded": False, "views": None}])
        self.assertEqual(self.app._dir_maps, [("p.w3x", "地图甲")])  # 对战列表没被清
        self.assertEqual(len(self.app._dir_campaigns), 1)

    def test_switching_back_to_battle_restores_dir_list(self):
        self.app._dir_maps = [("p1.w3x", "地图甲")]
        top = MapData(path="a.w3n", name="战役A")
        self.app._set_campaign_views([("★共享", top)], "a.w3n")
        self.assertEqual(self.app.mode, "campaign")
        self.app._on_mode_change("对战图")
        self.assertEqual(self.app.mode, "battle")
        self.assertEqual([self._label(i) for i in self._roots()], ["地图甲"])


if __name__ == "__main__":
    unittest.main()
