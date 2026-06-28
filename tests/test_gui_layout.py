"""编辑器风格 GUI 布局测试。"""
import unittest

from PIL import Image

from tests.gui_base import GuiTestCase
from w3xtool.api import GameObject, MapData
from w3xtool.load_options import default_load_options, object_only_load_options


def _visible_texts(widget):
    texts = []
    for child in widget.winfo_children():
        if child.__class__.__name__ in {"CTkLabel", "CTkButton"}:
            text = child.cget("text")
            if text:
                texts.append(text)
        texts.extend(_visible_texts(child))
    return texts


def _descendants(widget):
    children = []
    for child in widget.winfo_children():
        children.append(child)
        children.extend(_descendants(child))
    return children


class TestEditorStyleLayout(GuiTestCase):
    def test_editor_tabs_are_present(self):
        # Given: the GUI has been constructed.
        expected = (
            "总览", "对象编辑器", "地图信息", "场景放置", "触发指令",
            "合成配方", "孤立对象", "分析报告", "加载设置",
        )

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

    def test_reports_render_as_readable_cards(self):
        # Given: a loaded map with overview and warning content.
        md = MapData(path="x.w3x", name="卡片测试图")
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

        # When: the reports are refreshed.
        self.app._render_map(md, [], [], None)

        # Then: visible card widgets replace the unreadable raw textbox surface.
        self.assertGreaterEqual(len(self.app.overview_cards), 3)
        self.assertGreaterEqual(len(self.app.analysis_cards), 1)
        self.assertEqual(self.app.overview_box.winfo_ismapped(), 0)
        self.assertEqual(self.app.analysis_box.winfo_ismapped(), 0)

    def test_object_gallery_uses_name_only_dense_cards(self):
        # Given: enough items to fill more than one dense gallery row.
        md = MapData(path="x.w3x", name="对象密度测试图")
        md.objects = {
            "物品": [
                GameObject(
                    category="物品",
                    ext="w3t",
                    obj_id=f"I00{i}",
                    base_id=f"I00{i}",
                    name=f"物品{i}",
                    is_custom=True,
                    fields=[("名称", f"物品{i}")],
                )
                for i in range(6)
            ]
        }
        self.app.active_object_category = "物品"

        # When: the object gallery is rendered.
        self.app._render_map(md, [], [], None)
        self.pump_events_until(lambda: len(self.app.object_cards.winfo_children()) >= 6)
        cards = self.app.object_cards.winfo_children()

        # Then: cards are name-only rows; all metadata belongs in the right detail panel.
        self.assertGreaterEqual(len(cards), 6)
        self.assertLessEqual(int(cards[0].cget("height")), 44)
        self.assertEqual(_visible_texts(cards[0]), ["物品0"])
        self.assertFalse(
            any(child.__class__.__name__ == "CTkButton" for child in _descendants(cards[0]))
        )
        self.assertEqual(cards[3].grid_info()["row"], 0)
        self.assertEqual(cards[3].grid_info()["column"], 3)
        self.assertEqual(cards[4].grid_info()["row"], 1)

    def test_object_gallery_batches_large_categories_for_fast_switching(self):
        # Given: a large category like real RPG maps on Windows.
        md = MapData(path="x.w3x", name="切换性能测试图")
        md.objects = {
            "物品": [
                GameObject(
                    category="物品",
                    ext="w3t",
                    obj_id=f"I{i:03d}",
                    base_id=f"I{i:03d}",
                    name=f"物品{i}",
                    is_custom=True,
                )
                for i in range(100)
            ]
        }
        self.app.active_object_category = "物品"

        # When: the object gallery is rendered.
        self.app._render_map(md, [], [], None)
        self.pump_events_until(lambda: len(self.app.col_results["物品"]) == 100)
        widgets = self.app.object_cards.winfo_children()

        # Then: category switching does not synchronously create every card.
        self.assertLess(len(widgets), 100)
        self.assertLessEqual(len(self.app.col_trees["物品"].get_children()), 32)
        buttons = [widget for widget in widgets if widget.__class__.__name__ == "CTkButton"]
        self.assertTrue(any("加载更多" in button.cget("text") for button in buttons))

    def test_object_icon_loads_only_when_detail_is_opened(self):
        # Given: an object has an icon and the gallery is rendered.
        resolver = _FakeIconResolver()
        obj = GameObject(
            category="物品",
            ext="w3t",
            obj_id="I000",
            base_id="I000",
            name="图标物品",
            is_custom=True,
            icon="ReplaceableTextures\\CommandButtons\\BTNItem.blp",
        )
        md = MapData(path="x.w3x", name="图标测试图", objects={"物品": [obj]})

        # When: the map renders, then the user opens details for that object.
        self.app._render_map(md, [], [], resolver)
        calls_after_render = list(resolver.calls)
        self.app._show_detail(obj)

        # Then: the object list did not decode the icon; the detail panel did.
        self.assertEqual(calls_after_render, [])
        self.assertEqual(resolver.calls, [obj.icon])
        self.assertIsNotNone(self.app.detail_icon_image)

    def test_object_only_load_options_skip_other_views(self):
        # Given: only the object browser is enabled.
        self.app._apply_load_options(object_only_load_options(), persist=False, refresh=False)
        md = MapData(
            path="x.w3x",
            name="按需渲染测试图",
            objects={"物品": [GameObject("物品", "w3t", "I000", "I000", "物品", True)]},
        )

        # When: a map renders with commands and recipes provided by the loader.
        self.app._render_map(md, ["-debug"], ["recipe"], None)
        self.pump_events_until(lambda: len(self.app.object_cards.winfo_children()) >= 1)

        # Then: the object browser renders, while disabled views stay empty.
        self.assertGreaterEqual(len(self.app.object_cards.winfo_children()), 1)
        self.assertEqual(self.app.commands, [])
        self.assertEqual(self.app.recipes, [])
        self.assertEqual(len(self.app.cmd_tree.get_children()), 0)
        self.assertIn("加载设置", self.app.cmd_hint.cget("text"))
        self.app._apply_load_options(default_load_options(), persist=False, refresh=False)


class _FakeIconResolver:
    def __init__(self):
        self.calls = []

    def get_image(self, path):
        self.calls.append(path)
        return Image.new("RGBA", (16, 16), (255, 64, 128, 255))


if __name__ == "__main__":
    unittest.main()
