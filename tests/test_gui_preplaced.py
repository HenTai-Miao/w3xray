"""GUI 预放置标签页测试：列出 war3mapUnits.doo 单位与 war3map.doo 装饰物，可搜索。"""
import unittest

from tests.gui_base import GuiTestCase
from w3xtool.api import MapData
from w3xtool.doo import Unit, Doodad


def _md_with_preplaced():
    md = MapData(path="x", name="x")
    md.units = [
        Unit(type_id="Hblm", variation=0, x=10.0, y=20.0, z=0.0, angle=0.0,
             player=1, hp=500, mana=100, gold=0, hero_level=3),
        Unit(type_id="hpea", variation=0, x=30.0, y=40.0, z=0.0, angle=0.0,
             player=0, hp=-1, mana=-1, gold=0, hero_level=1),
    ]
    md.doodads = [
        Doodad(type_id="LTlt", variation=0, x=1.0, y=2.0, z=0.0, angle=0.0,
               life=100, serial=1),
    ]
    return md


class TestPreplacedTab(GuiTestCase):
    def test_units_and_doodads_listed(self):
        self.app.map_data = _md_with_preplaced()
        self.app._refresh_preplaced()
        self.assertEqual(len(self.app.unit_tree.get_children()), 2)
        self.assertEqual(len(self.app.doodad_tree.get_children()), 1)

    def test_search_filters_units_by_id(self):
        self.app.map_data = _md_with_preplaced()
        self.app.pre_search.set("hpea")
        self.app._refresh_preplaced()
        rows = self.app.unit_tree.get_children()
        self.assertEqual(len(rows), 1)
        # 命中的那行应包含玩家/坐标信息
        vals = self.app.unit_tree.item(rows[0], "values")
        self.assertIn("hpea", " ".join(str(v) for v in vals))

    def test_empty_query_shows_all(self):
        self.app.map_data = _md_with_preplaced()
        self.app.pre_search.set("")
        self.app._refresh_preplaced()
        self.assertEqual(len(self.app.unit_tree.get_children()), 2)

    def test_no_map_is_noop(self):
        self.app.map_data = None
        self.app._refresh_preplaced()   # 不应抛
        self.assertEqual(len(self.app.unit_tree.get_children()), 0)


if __name__ == "__main__":
    unittest.main()
