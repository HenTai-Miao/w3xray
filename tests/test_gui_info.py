"""GUI 地图信息标签页：展示 war3map.w3i 解析出的名/作者/玩家/脚本语言等。"""
import unittest

from tests.gui_base import GuiTestCase
from w3xtool.api import MapData
from w3xtool.w3i import W3iInfo, Player, Force


class TestInfoTab(GuiTestCase):
    def _text(self):
        return self.app.info_box.get("1.0", "end")

    def test_info_rendered(self):
        info = W3iInfo(version=25, map_name="测试图", author="老王",
                       description="一句话", recommended_players="1-4",
                       width=128, height=128, melee=True, script_type="Lua")
        info.players = [Player(0, 1, 1, 0, "玩家甲"), Player(1, 2, 2, 0, "电脑乙")]
        info.forces = [Force(name="队伍A", allied=True, players=[1, 2])]
        md = MapData(path="x", name="测试图")
        md.w3i = info
        self.app.map_data = md
        self.app._refresh_info()
        txt = self._text()
        self.assertIn("老王", txt)
        self.assertIn("玩家甲", txt)
        self.assertIn("Lua", txt)
        self.assertIn("队伍A", txt)

    def test_no_w3i_shows_placeholder(self):
        md = MapData(path="x", name="无信息图")
        md.w3i = None
        self.app.map_data = md
        self.app._refresh_info()        # 不应抛
        self.assertIn("无", self._text())


if __name__ == "__main__":
    unittest.main()
