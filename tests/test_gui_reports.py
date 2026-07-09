"""GUI 总览/分析报告的纯数据格式化。"""
import unittest

from w3xtool.api import GameObject, MapData
from w3xtool.gameconfig import GameConfiguration, GameConfigPlayer, NamedGameConfiguration
from w3xtool.gui_reports import build_analysis_blocks, build_overview_blocks, format_blocks
from w3xtool.imp import ImportEntry, ImportSummary
from w3xtool.mmp import PreviewIcon, PreviewIconSummary
from w3xtool.wtg import TriggerCategory, TriggerHeader, TriggerTreeSummary, TriggerVariable


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

    def test_reports_include_game_config_details(self):
        # Given: a map with an internal World Editor AI test configuration.
        md = MapData(path="x.w3x", name="配置图")
        md.game_configs = [
            NamedGameConfiguration(
                "testconfig.wgc",
                GameConfiguration(
                    format_version=1,
                    flags=0x01,
                    base_speed=4,
                    map_path="Maps\\Anime\\Test.w3x",
                    players=(GameConfigPlayer(1, 0, 0x02, 1, 90, 0x04, 2, "AI Scripts\\rush.ai"),),
                ),
            )
        ]

        # When: overview and analysis blocks are formatted.
        overview = format_blocks(build_overview_blocks(md))
        analysis = format_blocks(build_analysis_blocks(md))

        # Then: both surfaces make the configuration discoverable.
        self.assertIn("游戏配置 1", overview)
        self.assertIn("testconfig.wgc", analysis)
        self.assertIn("400%", analysis)
        self.assertIn("AI Scripts\\rush.ai", analysis)

    def test_reports_include_trigger_tree_details(self):
        # Given: parsed trigger metadata from war3map.wtg.
        md = MapData(path="x.w3x", name="触发图")
        md.trigger_summary = TriggerTreeSummary(
            version=7,
            is_reforged=True,
            category_count=1,
            variable_count=1,
            trigger_count=1,
            comment_count=1,
            script_count=1,
            categories=(TriggerCategory(1, "系统"),),
            variables=(TriggerVariable("Count", "integer", 1, False, 1, True, "5"),),
            triggers=(TriggerHeader("初始化", "", False, True, False, False, True, 1, 0),),
        )

        # When: overview and analysis blocks are formatted.
        overview = format_blocks(build_overview_blocks(md))
        analysis = format_blocks(build_analysis_blocks(md))

        # Then: WTG metadata appears in the editor reports.
        self.assertIn("触发器树 1", overview)
        self.assertIn("触发器树", analysis)
        self.assertIn("系统", analysis)
        self.assertIn("Count", analysis)

    def test_reports_include_preview_icons(self):
        # Given: parsed minimap preview icons.
        md = MapData(path="x.w3x", name="标记图")
        md.preview_icons = PreviewIconSummary(
            version=0,
            icons=(
                PreviewIcon(2, 12, 34, (255, 0, 0), 255),
                PreviewIcon(0, 80, 90, (255, 215, 0), 255),
            ),
        )

        # When: overview and analysis blocks are formatted.
        overview = format_blocks(build_overview_blocks(md))
        analysis = format_blocks(build_analysis_blocks(md))

        # Then: preview icon counts are visible in GUI reports.
        self.assertIn("小地图标记 2", overview)
        self.assertIn("小地图标记", analysis)
        self.assertIn("玩家出生点", analysis)
        self.assertIn("金矿 1", analysis)

    def test_reports_include_save_and_id_investigation_clues(self):
        # Given: a script with local save-style APIs and object IDs.
        md = MapData(path="x.w3x", name="存档图")
        md.objects = {
            "技能": [
                GameObject("技能", "w3a", "A001", "AHhb", "治疗术", True),
            ]
        }
        md.scripts = {
            "war3map.j": "\n".join((
                'set udg_cache = InitGameCache("AnimeSave.w3v")',
                'call StoreInteger(udg_cache, "hero", "level", 1)',
                'call PreloadGenEnd("save\\hero.txt")',
                "call UnitAddAbility(u, 'A001')",
            )),
        }

        # When: analysis blocks are formatted.
        analysis = format_blocks(build_analysis_blocks(md))

        # Then: the GUI exposes save/resource investigation clues in one card.
        self.assertIn("存档/ID线索", analysis)
        self.assertIn("AnimeSave.w3v", analysis)
        self.assertIn("save\\hero.txt", analysis)
        self.assertIn("A001", analysis)

    def test_reports_include_resource_inventory_statuses(self):
        # Given: a map with UI files, imported resources, and a missing import.
        md = MapData(path="x.w3x", name="资源图")
        md.objects = {
            "单位": [
                GameObject(
                    category="单位",
                    ext="w3u",
                    obj_id="H001",
                    base_id="Hpal",
                    name="英雄",
                    is_custom=True,
                    fields=[("模型", "war3mapImported\\Hero.mdx")],
                    icon="ReplaceableTextures\\CommandButtons\\BTNHero.blp",
                )
            ]
        }
        md.all_files = ["war3map.wts", "war3mapImported\\Hero.mdx"]
        md.import_summary = ImportSummary(
            version=1,
            entries=(
                ImportEntry(path="Hero.mdx", flag=8),
                ImportEntry(path="ReplaceableTextures\\Missing.blp", flag=13),
            ),
            resolved_paths=("war3mapImported\\Hero.mdx",),
            missing_paths=("ReplaceableTextures\\Missing.blp",),
        )

        # When: analysis blocks are formatted.
        analysis = format_blocks(build_analysis_blocks(md))

        # Then: the GUI exposes the same resource inventory statuses as the pack.
        self.assertIn("资源资产", analysis)
        self.assertIn("UI/文本 1", analysis)
        self.assertIn("导入缺失", analysis)
        self.assertIn("replaceabletextures\\missing.blp", analysis)

    def test_reports_include_ui_text_summary(self):
        # Given: a map with WTS UI strings and trigger references.
        md = MapData(path="x.w3x", name="文本图")
        md.scripts = {
            "war3map.wts": "STRING 1\n{\n开始游戏\n}\n",
            "war3map.j": (
                'call BJDebugMsg("TRIGSTR_001")\n'
                'call BJDebugMsg("TRIGSTR_999")\n'
            ),
        }

        # When: analysis blocks are formatted.
        analysis = format_blocks(build_analysis_blocks(md))

        # Then: UI text extraction is visible without exporting the pack.
        self.assertIn("UI文本", analysis)
        self.assertIn("字符串 1", analysis)
        self.assertIn("引用 2", analysis)
        self.assertIn("未解析 1", analysis)
        self.assertIn("TRIGSTR_001", analysis)

    def test_reports_include_extraction_completeness_summary(self):
        # Given: parsed map data with an internal file list but no readable source archive.
        md = MapData(path="/missing/map.w3x", name="提取图")
        md.all_files = ["war3map.j", "war3map.w3i"]

        # When: analysis blocks are formatted.
        analysis = format_blocks(build_analysis_blocks(md))

        # Then: users can tell why only filename-level extraction data is available.
        self.assertIn("提取完整性", analysis)
        self.assertIn("命名文件 2", analysis)
        self.assertIn("源文件不可读", analysis)

    def test_reports_include_script_mechanism_need_marks(self):
        # Given: script helpers that depend on Blizzard runtime object pools.
        md = MapData(path="x.w3x", name="机制图")
        md.scripts = {"war3map.j": "call ChooseRandomItemBJ(3)\ncall InitNeutralBuildings()\n"}

        # When: analysis blocks are formatted.
        analysis = format_blocks(build_analysis_blocks(md))

        # Then: the GUI exposes these mechanisms without inventing fixed object IDs.
        self.assertIn("脚本机制", analysis)
        self.assertIn("随机物品池", analysis)
        self.assertIn("中立建筑初始化", analysis)


if __name__ == "__main__":
    unittest.main()
