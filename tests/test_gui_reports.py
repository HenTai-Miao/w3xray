"""GUI 总览/分析报告的纯数据格式化。"""
import unittest

from w3xtool.api import GameObject, MapData
from w3xtool.gui_reports import build_analysis_blocks, build_overview_blocks, format_blocks


class GuiReportTest(unittest.TestCase):
    def test_overview_summarizes_editor_inventory(self):
        # Given: a loaded map with objects, scripts, commands, recipes, and placements.
        md = MapData(path="x.w3x", name="测试图")
        md.objects = {
            "单位": [
                GameObject(
                    category="单位",
                    ext="w3u",
                    obj_id="H001",
                    base_id="H001",
                    name="英雄",
                    is_custom=True,
                )
            ],
            "技能": [],
        }
        md.scripts = {"war3map.j": "function main takes nothing returns nothing\nendfunction"}
        md.script_features = ["对战开局"]

        # When: overview blocks are built for the editor-style dashboard.
        text = format_blocks(build_overview_blocks(md, command_count=2, recipe_count=1))

        # Then: the summary reads like a map editor inventory.
        self.assertIn("测试图", text)
        self.assertIn("单位 1", text)
        self.assertIn("聊天指令 2", text)
        self.assertIn("合成配方 1", text)
        self.assertIn("对战开局", text)

    def test_analysis_groups_crash_and_cheat_risks(self):
        # Given: a map with a known crash risk and a cheat phrase residue.
        md = MapData(path="x.w3x", name="风险图")
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
        md.scripts = {
            "war3map.j": (
                'call TriggerRegisterPlayerChatEvent(gg_trg_Debug, Player(0), "whosyourdaddy", true)'
            )
        }

        # When: analysis blocks are built.
        blocks = build_analysis_blocks(md)
        text = format_blocks(blocks)

        # Then: high-value risk classes are visible as separate editor report blocks.
        self.assertTrue(any(block.warning_count > 0 for block in blocks))
        self.assertIn("崩溃风险", text)
        self.assertIn("秘籍/调试口令", text)
        self.assertIn("闪电链", text)
        self.assertIn("whosyourdaddy", text)


if __name__ == "__main__":
    unittest.main()
