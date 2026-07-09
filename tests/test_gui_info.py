"""GUI 地图信息标签页：展示 war3map.w3i 解析出的名/作者/玩家/脚本语言等。"""
import unittest

from tests.gui_base import GuiTestCase
from w3xtool.api import MapData
from w3xtool.gameconfig import GameConfiguration, GameConfigPlayer, NamedGameConfiguration
from w3xtool.imp import ImportEntry, ImportSummary
from w3xtool.mmp import PreviewIcon, PreviewIconSummary
from w3xtool.w3i import W3iInfo, Player, Force
from w3xtool.w3world import Camera, Region, Sound
from w3xtool.wtg import (
    TriggerCategory,
    TriggerHeader,
    TriggerParseFailure,
    TriggerTreeSummary,
    TriggerVariable,
    UnknownTriggerFunction,
)


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

    def test_world_metadata_rendered(self):
        md = MapData(path="x", name="世界数据图")
        md.regions = [Region(0, 0, 128, 128, "出生区", 1, "", "", (255, 0, 0), 255)]
        md.cameras = [Camera(0, 0, 0, 0, 304, 1650, 0, 70, 5000, 100, "开场镜头")]
        md.sounds = [Sound("导入声", "war3mapImported\\voice.wav", "", 16, 0, 0, 127,
                           1.0, 0, 100, 1000, 3000)]
        self.app.map_data = md
        self.app._refresh_info()
        txt = self._text()
        self.assertIn("世界编辑器数据", txt)
        self.assertIn("出生区", txt)
        self.assertIn("开场镜头", txt)
        self.assertIn("导入声", txt)

    def test_game_config_rendered(self):
        md = MapData(path="x", name="配置图")
        md.game_configs = [
            NamedGameConfiguration(
                "testconfig.wgc",
                GameConfiguration(
                    format_version=1,
                    flags=0x02,
                    base_speed=4,
                    map_path="Maps\\Anime\\Test.w3x",
                    players=(GameConfigPlayer(0, 0, 0x02, 1, 90, 0x04, 2, "AI Scripts\\rush.ai"),),
                ),
            )
        ]
        self.app.map_data = md
        self.app._refresh_info()
        txt = self._text()
        self.assertIn("游戏配置", txt)
        self.assertIn("testconfig.wgc", txt)
        self.assertIn("禁用胜负条件", txt)
        self.assertIn("AI Scripts\\rush.ai", txt)

    def test_trigger_tree_rendered(self):
        md = MapData(path="x", name="触发图")
        md.trigger_summary = TriggerTreeSummary(
            version=7,
            is_reforged=False,
            category_count=1,
            variable_count=1,
            trigger_count=1,
            comment_count=0,
            script_count=0,
            categories=(TriggerCategory(42, "系统"),),
            variables=(TriggerVariable("Count", "integer", 1, False, 1, True, "5"),),
            triggers=(TriggerHeader("初始化", "", False, True, False, False, True, 42, 0),),
            has_unexpanded_functions=True,
            missing_schema_functions=(UnknownTriggerFunction("初始化", "MissingAction", 2, 0x44),),
            parse_failures=(TriggerParseFailure("初始化", "BadAction", 0x88, "bad bytes"),),
        )
        self.app.map_data = md
        self.app._refresh_info()
        txt = self._text()
        self.assertIn("触发器树", txt)
        self.assertIn("系统", txt)
        self.assertIn("初始化", txt)
        self.assertIn("缺少 TriggerData/TriggerStrings", txt)
        self.assertIn("MissingAction", txt)
        self.assertIn("WTG 解析失败", txt)
        self.assertIn("BadAction @ 0x88", txt)

    def test_preview_icons_rendered(self):
        md = MapData(path="x", name="标记图")
        md.preview_icons = PreviewIconSummary(
            version=0,
            icons=(
                PreviewIcon(2, 12, 34, (255, 0, 0), 255),
                PreviewIcon(1, 120, 150, (80, 160, 255), 255),
            ),
        )
        self.app.map_data = md
        self.app._refresh_info()
        txt = self._text()
        self.assertIn("小地图标记", txt)
        self.assertIn("玩家出生点", txt)
        self.assertIn("中立建筑", txt)

    def test_import_summary_rendered(self):
        md = MapData(path="x", name="导入图")
        md.import_summary = ImportSummary(
            version=1,
            entries=(
                ImportEntry("icon.blp", 8),
                ImportEntry("ReplaceableTextures\\custom.blp", 13),
            ),
            resolved_paths=("war3mapImported\\icon.blp",),
            missing_paths=("ReplaceableTextures\\custom.blp",),
        )
        self.app.map_data = md
        self.app._refresh_info()
        txt = self._text()
        self.assertIn("导入资源", txt)
        self.assertIn("自定义路径", txt)
        self.assertIn("ReplaceableTextures\\custom.blp", txt)


if __name__ == "__main__":
    unittest.main()
