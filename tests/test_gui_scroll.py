"""各表格横向滚动 + 列宽随内容自适应（长名字/长说明也能看全），
以及切图时释放上一个图标解析器、无指令时提示文案更新。"""
import unittest

from tests.gui_base import GuiTestCase
from w3xtool.api import MapData, GameObject
from w3xtool.script_scan import ChatCommand


def _obj(name, cat="物品"):
    return GameObject(category=cat, ext="w3t", obj_id="I000", base_id="I000",
                      name=name, is_custom=True, fields=[], search_text=name, icon="")


class TestHScrollExists(GuiTestCase):
    def test_map_list_has_hscroll(self):
        self.assertTrue(self.app.map_list.cget("xscrollcommand"),
                        "地图列表缺少横向滚动条")

    def test_object_columns_have_hscroll(self):
        for cat, tv in self.app.col_trees.items():
            self.assertTrue(tv.cget("xscrollcommand"), f"{cat} 列缺少横向滚动条")

    def test_cmd_tree_has_hscroll(self):
        self.assertTrue(self.app.cmd_tree.cget("xscrollcommand"),
                        "隐藏指令表缺少横向滚动条")


class TestColumnAutosize(GuiTestCase):
    def test_object_column_grows_for_long_name(self):
        tv = self.app.col_trees["物品"]
        base = int(tv.column("#0", "width"))
        long_name = "超级无敌究极霸天虎传说之剑·永恒星辰·限定版×" * 3
        self.app.map_data = MapData(path="x", name="x",
                                    objects={"物品": [_obj(long_name)]})
        self.app.icons = None
        self.app._refresh_list()
        self.assertGreater(int(tv.column("#0", "width")), base,
                           "物品列宽未随长名字增长")

    def test_cmd_hint_column_grows_for_long_hint(self):
        base = int(self.app.cmd_tree.column("hint", "width"))
        self.app.commands = [ChatCommand("-x", False, "", "前缀" * 200)]
        self.app._refresh_cmds()
        self.assertGreater(int(self.app.cmd_tree.column("hint", "width")), base,
                           "指令说明列宽未随长说明增长")


class TestCmdHintNoCommands(GuiTestCase):
    def test_hint_updates_when_no_commands(self):
        self.app.commands = []
        self.app._refresh_cmds()
        txt = self.app.cmd_hint.cget("text")
        self.assertIn("未", txt)        # 应提示"未发现/未识别"之类，而非残留上张图统计


class _FakeResolver:
    def __init__(self):
        self.closed = False

    def get_image(self, p):
        return None

    def close(self):
        self.closed = True


class TestResolverClosedOnSwitch(GuiTestCase):
    def test_old_resolver_closed_when_new_map_rendered(self):
        old = _FakeResolver()
        self.app.icons = old
        md = MapData(path="y", name="y")
        self.app._render_map(md, [], [], _FakeResolver())
        self.assertTrue(old.closed, "切换地图时未释放上一个图标解析器")


if __name__ == "__main__":
    unittest.main()
