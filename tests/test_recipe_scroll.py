"""合成配方表：横向滚动 + 材料列按内容自适应宽度（材料多时也能看全）。"""
import unittest

from tests.gui_base import GuiTestCase
from w3xtool.script_scan import Recipe


class TestRecipeScroll(GuiTestCase):
    def test_recipe_tree_has_hscroll(self):
        # 材料一长就被裁，必须有横向滚动条才能看全
        self.assertTrue(self.app.rec_tree.cget("xscrollcommand"),
                        "合成配方表缺少横向滚动条")

    def test_ingredient_column_grows_for_long_content(self):
        base = int(self.app.rec_tree.column("ingredients", "width"))
        # 一条材料超多的配方
        many = [f"I{i:03d}" for i in range(30)]
        self.app.recipes = [Recipe(many, "Ifin")]
        self.app._refresh_recipes()
        grown = int(self.app.rec_tree.column("ingredients", "width"))
        self.assertGreater(grown, base, "材料列没有随长内容变宽")


if __name__ == "__main__":
    unittest.main()
