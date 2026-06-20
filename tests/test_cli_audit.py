"""CLI 摘要输出包含地图智能审计结果。"""
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from main import iter_cli_summary_lines
from w3xtool.api import GameObject, MapData
from w3xtool.gameplay import GameplayConstant
from w3xtool.mapmeta import MapStructureReport, PathingSummary
from w3xtool.slkmeta import SlkFileSummary, SlkInventoryReport
from w3xtool.terrain import TerrainInfo


def _obj(category, obj_id):
    return GameObject(
        category=category,
        ext="w3u",
        obj_id=obj_id,
        base_id=obj_id,
        name=obj_id,
        is_custom=True,
    )


class CliAuditTest(unittest.TestCase):
    def test_cli_summary_includes_audit_warning(self):
        # Given: a map missing war3map.w3i.
        md = MapData(path="x.w3x", name="测试图")
        md.objects = {"单位": [_obj("单位", "H001")]}

        # When: CLI summary lines are rendered.
        lines = list(iter_cli_summary_lines(md))

        # Then: audit warnings are visible in the CLI output.
        self.assertIn("地图: 测试图", lines)
        self.assertIn("  审计:", lines)
        self.assertTrue(any("缺少地图信息" in line for line in lines))

    def test_cli_summary_keeps_existing_category_counts(self):
        # Given: a map with normal metadata and one category count.
        md = MapData(path="x.w3x", name="测试图")
        md.w3i = SimpleNamespace(
            author="作者",
            script_type="JASS",
            players=[],
            forces=[],
            width=64,
            height=64,
        )
        md.objects = {"技能": [_obj("技能", "A001")]}
        md.scripts = {"war3map.j": "function main takes nothing returns nothing\nendfunction"}

        # When: CLI summary lines are rendered.
        lines = list(iter_cli_summary_lines(md))

        # Then: the original category line remains, with audit info appended.
        self.assertIn("  技能: 1", lines)
        self.assertTrue(any("主脚本" in line for line in lines))

    def test_cli_summary_includes_resource_and_compat_blocks(self):
        # Given: a map with one referenced model and one newer Lua compatibility risk.
        md = MapData(path="x.w3x", name="测试图")
        md.w3i = SimpleNamespace(
            author="作者",
            script_type="Lua",
            players=[],
            forces=[],
            width=64,
            height=64,
            version=28,
            large_map=False,
        )
        md.objects = {
            "单位": [
                GameObject(
                    category="单位",
                    ext="w3u",
                    obj_id="H001",
                    base_id="H001",
                    name="英雄",
                    is_custom=True,
                    fields=[("模型", "war3mapImported\\Hero.mdx")],
                )
            ]
        }
        md.scripts = {"war3map.lua": "print('x')"}
        md.all_files = ["war3mapImported\\Hero.mdx", "war3mapImported\\unused.blp"]

        # When: CLI summary lines are rendered.
        lines = list(iter_cli_summary_lines(md))

        # Then: resource and compatibility sections are both visible.
        self.assertIn("  资源:", lines)
        self.assertIn("  兼容:", lines)
        self.assertTrue(any("未引用素材" in line for line in lines))
        self.assertTrue(any("Lua 脚本不兼容" in line for line in lines))

    def test_cli_summary_includes_order_collisions(self):
        # Given: two abilities reuse the same order string.
        md = MapData(path="x.w3x", name="测试图")
        md.objects = {
            "技能": [
                GameObject(
                    category="技能",
                    ext="w3a",
                    obj_id="A001",
                    base_id="A001",
                    name="火球",
                    is_custom=True,
                    fields=[("命令串 - 使用/打开", "channel")],
                ),
                GameObject(
                    category="技能",
                    ext="w3a",
                    obj_id="A002",
                    base_id="A002",
                    name="冰箭",
                    is_custom=True,
                    fields=[("命令串 - 使用/打开", "channel")],
                ),
            ]
        }

        # When: CLI summary lines are rendered.
        lines = list(iter_cli_summary_lines(md))

        # Then: order collision details are visible.
        self.assertIn("  命令:", lines)
        self.assertTrue(any("channel" in line and "冲突" in line for line in lines))

    def test_cli_summary_includes_decoded_script_order_ids(self):
        # Given: a script uses a numeric order id from the public catalog.
        md = MapData(path="x.w3x", name="测试图")
        md.scripts = {"war3map.j": "call IssueImmediateOrderById(u, 852600)"}

        # When: CLI summary lines are rendered.
        lines = list(iter_cli_summary_lines(md))

        # Then: the decoded command name is visible.
        self.assertIn("  命令:", lines)
        self.assertTrue(any("channel" in line and "war3map.j" in line for line in lines))

    def test_cli_summary_includes_script_diagnostics(self):
        # Given: a script with local-player risk.
        md = MapData(path="x.w3x", name="测试图")
        md.scripts = {"war3map.j": "if GetLocalPlayer() == Player(0) then\nendif"}

        # When: CLI summary lines are rendered.
        lines = list(iter_cli_summary_lines(md))

        # Then: script diagnostics are shown.
        self.assertIn("  脚本诊断:", lines)
        self.assertTrue(any("本地玩家分支" in line for line in lines))

    def test_cli_summary_includes_crash_risks(self):
        # Given: a map contains a known crash-prone ability setting.
        md = MapData(path="x.w3x", name="测试图")
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

        # When: CLI summary lines are rendered.
        lines = list(iter_cli_summary_lines(md))

        # Then: crash risks are shown.
        self.assertIn("  崩溃风险:", lines)
        self.assertTrue(any("闪电链" in line and "1.24E" in line for line in lines))

    def test_cli_summary_includes_script_crash_risks(self):
        # Given: a script uses old game-cache APIs.
        md = MapData(path="x.w3x", name="测试图")
        md.scripts = {
            "war3map.j": (
                'set udg_cache = InitGameCache("mission.w3v")\n'
                'call StoreInteger(udg_cache, "MissionKey", "count", 1)\n'
            )
        }

        # When: CLI summary lines are rendered.
        lines = list(iter_cli_summary_lines(md))

        # Then: the script crash risk is visible.
        self.assertIn("  崩溃风险:", lines)
        self.assertTrue(any("游戏缓存" in line and "war3map.j" in line for line in lines))

    def test_cli_summary_includes_cheat_residue(self):
        # Given: a map contains an official cheat phrase in a chat trigger.
        md = MapData(path="x.w3x", name="测试图")
        md.scripts = {
            "war3map.j": (
                'call TriggerRegisterPlayerChatEvent(gg_trg_Debug, Player(0), "whosyourdaddy", true)'
            )
        }

        # When: CLI summary lines are rendered.
        lines = list(iter_cli_summary_lines(md))

        # Then: suspicious cheat/debug residue is visible.
        self.assertIn("  秘籍/调试口令:", lines)
        self.assertTrue(any("whosyourdaddy" in line and "聊天指令" in line for line in lines))

    def test_cli_summary_includes_terrain_block(self):
        # Given: a map whose terrain header can be read from the archive.
        md = MapData(path="x.w3x", name="测试图")
        info = TerrainInfo(
            version=11,
            base_tileset="L",
            custom_tilesets=True,
            ground_tiles=("Ldrt", "Ldro"),
            cliff_tiles=("CLdi",),
            width=65,
            height=33,
        )

        # When: CLI summary lines are rendered.
        with patch("w3xtool.terrain.terrain_info_from_map_path", return_value=info):
            lines = list(iter_cli_summary_lines(md))

        # Then: terrain texture and grid metadata is visible.
        self.assertIn("  地形:", lines)
        self.assertTrue(any("65×33" in line and "L" in line for line in lines))
        self.assertTrue(any("Ldrt" in line and "洛丹伦的夏天 - 泥地" in line for line in lines))
        self.assertTrue(any("TerrainArt\\LordaeronSummer\\Lords_Dirt.blp" in line for line in lines))

    def test_cli_summary_includes_return_bug_compat_warning(self):
        # Given: a map script using old 1.20E return-bug handle casting.
        md = MapData(path="x.w3x", name="测试图")
        md.w3i = SimpleNamespace(
            author="作者",
            script_type="JASS",
            players=[],
            forces=[],
            width=64,
            height=64,
            version=25,
            large_map=False,
        )
        md.scripts = {
            "war3map.j": (
                "function H2I takes handle h returns integer\n"
                "    return h\n"
                "    return 0\n"
                "endfunction\n"
            )
        }

        # When: CLI summary lines are rendered.
        lines = list(iter_cli_summary_lines(md))

        # Then: the compatibility block surfaces the 1.20E migration risk.
        self.assertIn("  兼容:", lines)
        self.assertTrue(any("return bug" in line and "H2I" in line for line in lines))

    def test_cli_summary_includes_map_structure_block(self):
        # Given: a map with parsed internal structure summaries.
        md = MapData(path="x.w3x", name="测试图")
        report = MapStructureReport(
            regions=2,
            cameras=3,
            sounds=4,
            pathing=PathingSummary(width=8, height=9, cells=72),
            region_strings=("BossRoom",),
            camera_strings=("IntroCam",),
            sound_strings=("war3mapImported\\boss.mp3",),
        )

        # When: CLI summary lines are rendered.
        with patch("w3xtool.mapmeta.map_structure_report_from_map_path", return_value=report):
            lines = list(iter_cli_summary_lines(md))

        # Then: the structure block is visible.
        self.assertIn("  地图结构:", lines)
        self.assertTrue(any("区域: 2" in line and "镜头: 3" in line for line in lines))
        self.assertTrue(any("路径图: 8×9" in line for line in lines))
        self.assertTrue(any("BossRoom" in line for line in lines))
        self.assertTrue(any("IntroCam" in line for line in lines))
        self.assertTrue(any("boss.mp3" in line for line in lines))

    def test_cli_summary_includes_slk_inventory_block(self):
        # Given: parsed embedded SLK inventory from the map archive.
        md = MapData(path="x.w3x", name="测试图")
        report = SlkInventoryReport((
            SlkFileSummary(path="Units\\UnitData.slk", rows=12, columns=8),
            SlkFileSummary(path="AbilityData.slk", rows=4, columns=6),
        ))

        # When: CLI summary lines are rendered.
        with patch("w3xtool.slkmeta.slk_inventory_from_map_path", return_value=report):
            lines = list(iter_cli_summary_lines(md))

        # Then: the SLK table inventory is visible.
        self.assertIn("  SLK:", lines)
        self.assertTrue(any("Units\\UnitData.slk" in line and "12 行" in line for line in lines))
        self.assertTrue(any("AbilityData.slk" in line and "4 行" in line for line in lines))

    def test_cli_summary_includes_gameplay_constants_block(self):
        # Given: parsed gameplay constants from war3mapMisc.txt.
        md = MapData(path="x.w3x", name="测试图")
        constants = (
            GameplayConstant(section="Misc", key="HeroMaxLevel", value="20"),
            GameplayConstant(section="Combat", key="DamageBonus", value="1.25"),
        )

        # When: CLI summary lines are rendered.
        with patch("w3xtool.gameplay.gameplay_constants_from_map_path", return_value=constants):
            lines = list(iter_cli_summary_lines(md))

        # Then: detailed constants are visible.
        self.assertIn("  游戏常数:", lines)
        self.assertTrue(any("HeroMaxLevel=20" in line for line in lines))


if __name__ == "__main__":
    unittest.main()
