"""表格右键复制：隐藏指令/合成配方/对象列 选中行可复制到剪贴板。"""
import unittest

from tests.gui_base import GuiTestCase


class TestTreeCopy(GuiTestCase):
    def test_copy_command_row(self):
        self.app.cmd_tree.insert("", "end", iid="0", values=("-kill", "精确", "杀死单位"))
        self.app.cmd_tree.selection_set("0")
        self.app._copy_tree_row(self.app.cmd_tree)
        clip = self.app.clipboard_get()
        self.assertIn("-kill", clip)
        self.assertIn("杀死单位", clip)

    def test_copy_recipe_row(self):
        self.app.rec_tree.insert("", "end", iid="0", values=("圣剑", "铁剑 + 宝石"))
        self.app.rec_tree.selection_set("0")
        self.app._copy_tree_row(self.app.rec_tree)
        clip = self.app.clipboard_get()
        self.assertIn("圣剑", clip)
        self.assertIn("宝石", clip)

    def test_copy_object_name_row(self):
        tv = self.app.col_trees["物品"]
        tv.insert("", "end", iid="0", text=" 治疗药水")
        tv.selection_set("0")
        self.app._copy_tree_row(tv)
        self.assertIn("治疗药水", self.app.clipboard_get())


if __name__ == "__main__":
    unittest.main()
