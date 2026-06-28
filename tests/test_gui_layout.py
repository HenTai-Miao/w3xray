"""编辑器风格 GUI 布局测试。"""
import unittest

from PIL import Image

from tests.gui_base import GuiTestCase
from w3xtool.api import GameObject, MapData
from w3xtool.object_gallery import _show_selected_object
from w3xtool.script_scan import ChatCommand, Recipe


class TestEditorStyleLayout(GuiTestCase):
    def test_editor_tabs_are_present(self):
        # Given: the GUI has been constructed.
        expected = (
            "总览", "对象编辑器", "地图信息", "场景放置", "触发指令",
            "合成配方", "孤立对象", "分析报告",
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

    def test_object_gallery_shows_icon_and_name_in_one_fast_list(self):
        # Given: enough items to fill more than one dense list row.
        resolver = _FakeIconResolver()
        first_icon = "ReplaceableTextures\\CommandButtons\\BTNItem.blp"
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
                    icon=first_icon if i == 0 else "",
                )
                for i in range(6)
            ]
        }
        self.app.active_object_category = "物品"

        # When: the object gallery is rendered.
        self.app._render_map(md, [], [], resolver)
        self.pump_events_until(lambda: len(self.app.object_cards.get_children()) >= 6)
        rows = self.app.object_cards.get_children()

        # Then: all objects live in one fast list with icon and name only.
        self.assertEqual(self.app.object_cards.__class__.__name__, "Treeview")
        self.assertEqual(tuple(map(str, self.app.object_cards.cget("show"))), ("tree",))
        self.assertEqual(len(rows), 6)
        self.assertEqual(self.app.object_cards.item(rows[0], "text"), "物品0")
        self.assertEqual(self.app.object_cards.item(rows[3], "text"), "物品3")
        self.assertEqual(self.app.object_cards.cget("columns"), ())
        self.pump_events_until(lambda: bool(self.app.object_cards.item(rows[0], "image")))
        self.assertEqual(len(self.app.object_cards.winfo_children()), 0)

    def test_object_gallery_shows_every_object_in_current_category(self):
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
        self.pump_events_until(lambda: len(self.app.object_cards.get_children()) == 100)
        rows = self.app.object_cards.get_children()

        # Then: every object row in the active category is available without loading more.
        self.assertEqual(len(rows), 100)
        self.assertEqual(self.app.object_cards.item(rows[99], "text"), "物品99")
        self.assertLessEqual(len(self.app.col_trees["物品"].get_children()), 32)

    def test_object_gallery_exposes_all_object_editor_categories(self):
        # Given: a map has every object-editor category the parser supports.
        md = MapData(
            path="x.w3x",
            name="全对象分类测试图",
            objects={
                "单位": [GameObject("单位", "w3u", "H001", "H001", "步兵", True)],
                "物品": [GameObject("物品", "w3t", "I001", "I001", "药水", True)],
                "技能": [GameObject("技能", "w3a", "A001", "A001", "火球", True)],
                "科技": [GameObject("科技", "w3q", "R001", "R001", "升级", True)],
                "可破坏物": [GameObject("可破坏物", "w3b", "D001", "D001", "树木", True)],
                "装饰物": [GameObject("装饰物", "w3d", "B001", "B001", "雕像", True)],
                "增益": [GameObject("增益", "w3h", "F001", "F001", "眩晕", True)],
            },
        )
        self.app.active_object_category = "可破坏物"

        # When: the object gallery is rendered.
        self.app._render_map(md, [], [], None)
        self.pump_events_until(lambda: len(self.app.col_results["可破坏物"]) == 1)

        # Then: all supported object categories are selectable and render rows.
        for label in ("单位", "物品", "技能", "科技", "可破坏物", "装饰物", "增益"):
            self.assertIn(label, self.app.object_cat_buttons)
        first = self.app.object_cards.get_children()[0]
        self.assertEqual(self.app.object_cards.item(first, "text"), "树木")

    def test_object_gallery_selection_opens_detail_panel(self):
        # Given: a rendered object gallery with one selectable object.
        obj = GameObject(
            category="物品",
            ext="w3t",
            obj_id="I000",
            base_id="I000",
            name="详情物品",
            is_custom=True,
            fields=[("攻击", "+1")],
        )
        md = MapData(path="x.w3x", name="详情测试图", objects={"物品": [obj]})
        self.app.active_object_category = "物品"

        # When: the user selects the object in the fast list.
        self.app._render_map(md, [], [], None)
        self.pump_events_until(lambda: len(self.app.object_cards.get_children()) == 1)
        self.app.object_cards.selection_set("0")
        _show_selected_object(self.app.object_gallery, self.app._show_detail)

        # Then: the right detail panel shows the selected object.
        detail = self.app.detail.get("1.0", "end")
        self.assertIn("详情物品", detail)
        self.assertIn("攻击: +1", detail)

    def test_object_icon_loads_in_list_and_detail(self):
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
        self.app.active_object_category = "物品"

        # When: the map renders, then the user opens details for that object.
        self.app._render_map(md, [], [], resolver)
        self.pump_events_until(lambda: resolver.calls == [obj.icon])
        self.pump_events_until(lambda: bool(self.app.object_cards.item("0", "image")))
        calls_after_render = list(resolver.calls)
        self.app._show_detail(obj)

        # Then: the object list and detail panel both show the cached icon.
        self.assertEqual(calls_after_render, [obj.icon])
        self.assertEqual(resolver.calls, [obj.icon])
        self.assertEqual(self.app.object_gallery.icon_images[0].width(), 24)
        self.assertEqual(self.app.object_gallery.icon_images[0].height(), 24)
        self.assertIsNotNone(self.app.detail_icon_image)

    def test_removed_load_settings_defaults_all_views_to_enabled(self):
        # Given: the load settings tab has been removed from the visible workspace.
        md = MapData(
            path="x.w3x",
            name="默认加载测试图",
            objects={"物品": [GameObject("物品", "w3t", "I000", "I000", "物品", True)]},
        )

        # When: a map renders with commands and recipes provided by the loader.
        command = ChatCommand("-debug", True, "gg_trg_Debug", "调试")
        recipe = Recipe(["I000"], "I001")
        self.app._render_map(md, [command], [recipe], None)
        self.pump_events_until(lambda: len(self.app.object_cards.get_children()) >= 1)

        # Then: all major views render by default; there is no settings tab to hide them.
        self.assertGreaterEqual(len(self.app.object_cards.get_children()), 1)
        self.assertEqual(self.app.commands, [command])
        self.assertEqual(self.app.recipes, [recipe])
        self.assertNotIn("加载设置", self.app.editor_tab_labels)


class _FakeIconResolver:
    def __init__(self):
        self.calls = []

    def get_image(self, path):
        self.calls.append(path)
        return Image.new("RGBA", (16, 16), (255, 64, 128, 255))


if __name__ == "__main__":
    unittest.main()
