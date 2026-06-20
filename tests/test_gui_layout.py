"""编辑器风格 GUI 布局测试。"""
import unittest

from tests.gui_base import GuiTestCase
from w3xtool.api import GameObject, MapData


class TestEditorStyleLayout(GuiTestCase):
    def test_editor_tabs_are_present(self):
        # Given: the GUI has been constructed.
        expected = ("总览", "对象编辑器", "地图信息", "场景放置", "触发指令", "合成配方", "孤立对象", "分析报告")

        # When/Then: the editor-style workspace exposes the expected sections.
        self.assertEqual(self.app.editor_tab_labels, expected)
        for label in expected:
            self.app.tabs.tab(label)

    def test_render_map_refreshes_overview_and_analysis(self):
        # Given: a map that has inventory plus one crash risk.
        md = MapData(path="x.w3x", name="布局测试图")
        md.objects = {
            "技能": [
                GameObject(
                    category="技能",
                    ext="w3a",
                    obj_id="A001",
                    base_id="AOcl",
                    name="闪电链",
                    is_custom=True,
                    fields=[("每个目标伤害减少", "-1.00")],
                )
            ]
        }

        # When: the map is rendered into the GUI.
        self.app._render_map(md, [], [], None)

        # Then: the new editor dashboard and analysis report are populated.
        overview = self.app.overview_box.get("1.0", "end")
        analysis = self.app.analysis_box.get("1.0", "end")
        self.assertIn("布局测试图", overview)
        self.assertIn("技能 1", overview)
        self.assertIn("崩溃风险", analysis)
        self.assertIn("闪电链", analysis)


if __name__ == "__main__":
    unittest.main()
