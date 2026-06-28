"""GUI 测试共享单一 Tk 根。

一个进程内反复 `App()`（每次新建/销毁 Tcl 解释器）会间歇性抛
`_tkinter.TclError: Can't find a usable init.tcl` —— 实测 ~50% flaky。
改为整个测试会话只创建一个 App、各用例复用，便彻底消除重复创建。

所有 GUI 测试继承 `GuiTestCase`：`setUpClass` 取共享 App，`setUp` 把 App
复位回 `__init__` 的干净基线（清空各 Treeview、还原会被断言读取的列宽与
导航状态），App 在进程退出时统一销毁。
"""
import atexit
import unittest

from w3xtool.gui import App
from w3xtool.load_options import default_load_options

_APP = None


def _get_app() -> App:
    global _APP
    if _APP is None:
        _APP = App()
        _APP.withdraw()                 # 测试期间不弹窗
        atexit.register(_teardown)
    return _APP


def _teardown():
    global _APP
    if _APP is not None:
        try:
            _APP.destroy()
        except Exception:
            pass
        _APP = None


class GuiTestCase(unittest.TestCase):
    app: App

    @classmethod
    def setUpClass(cls):
        cls.app = _get_app()

    def setUp(self):
        app = self.app
        # 复位 __init__ 默认态（各 GUI 测试会自行覆盖所需字段）
        app.map_data = None
        app.recipes = []
        app._apply_load_options(default_load_options(), persist=False, refresh=False)
        app.mode = "battle"
        app._dir_maps = []
        app._dir_campaigns = []
        app._node_map = {}
        # 清空所有 Treeview，避免上个用例的行/iid 残留
        for tv in (app.map_list, app.cmd_tree, app.rec_tree,
                   app.unit_tree, app.doodad_tree, *app.col_trees.values()):
            tv.delete(*tv.get_children())
        app.pre_search.set("")
        # 地图信息框复位（只读 textbox 需临时切到可写态清空）
        app.info_box.configure(state="normal")
        app.info_box.delete("1.0", "end")
        app.info_box.configure(state="disabled")
        for box_name in ("overview_box", "analysis_box"):
            if hasattr(app, box_name):
                box = getattr(app, box_name)
                box.configure(state="normal")
                box.delete("1.0", "end")
                box.configure(state="disabled")
        # 材料列宽会被 test_ingredient_column_grows 读作基线，还原到初始 620
        app.rec_tree.column("ingredients", width=620)
