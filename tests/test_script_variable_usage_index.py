"""脚本变量使用索引：整理 udg_/gg_ 全局变量读写位置。"""

import importlib
import importlib.util
import unittest

from w3xtool.api import MapData


def _format_usage(md: MapData) -> str:
    spec = importlib.util.find_spec("w3xtool.script_variable_usage_index")
    if spec is None:
        raise AssertionError("w3xtool.script_variable_usage_index module is missing")
    module = importlib.import_module("w3xtool.script_variable_usage_index")
    index = module.build_script_variable_usage_index(md)
    return module.format_script_variable_usage_index_tsv(index)


class ScriptVariableUsageIndexTest(unittest.TestCase):
    def test_indexes_global_variable_reads_writes_and_categories(self):
        # Given: script code writes state and reads globals inside save/object logic.
        md = MapData(path="x.w3x", name="变量使用图")
        md.scripts = {
            "war3map.j": "\n".join((
                "function SaveHero takes nothing returns nothing",
                "    set udg_HeroId = 'H001'",
                "    call SaveInteger(udg_hash, StringHash(udg_SaveScope), StringHash(udg_SaveKey), udg_Level)",
                "    call TriggerRegisterPlayerEvent(gg_trg_Save, Player(0), EVENT_PLAYER_LEAVE)",
                "endfunction",
            )),
        }

        # When: the variable usage index is built.
        text = _format_usage(md)

        # Then: reads and writes are grouped with function context and variable category.
        self.assertIn("来源\t行号\t函数\t变量\t访问\t类别\t调用\t对象码\t摘要", text)
        self.assertIn("war3map.j\t2\tSaveHero\tudg_HeroId\t写入\t用户全局\t\tH001", text)
        self.assertIn("war3map.j\t3\tSaveHero\tudg_hash\t读取\t用户全局\tSaveInteger\t", text)
        self.assertIn("war3map.j\t3\tSaveHero\tudg_SaveKey\t读取\t用户全局\tSaveInteger\t", text)
        self.assertIn("war3map.j\t4\tSaveHero\tgg_trg_Save\t读取\t触发器变量\tTriggerRegisterPlayerEvent", text)

    def test_ignores_comments_strings_and_classifies_preplaced_globals(self):
        # Given: fake references appear in comments/strings while real preplaced globals are used.
        md = MapData(path="x.w3x", name="变量去噪图")
        md.scripts = {
            "war3map.j": "\n".join((
                "function Init takes nothing returns nothing",
                '// set udg_Bad = "comment"',
                '    call BJDebugMsg("udg_Fake")',
                "    call SetUnitOwner(gg_unit_Hero_0001, Player(0), true)",
                "    set bj_lastCreatedUnit = gg_unit_Hero_0001",
                "endfunction",
            )),
        }

        # When: the variable usage index is built.
        text = _format_usage(md)

        # Then: only real code references are indexed and categories are readable.
        self.assertIn("gg_unit_Hero_0001\t读取\t预放置单位\tSetUnitOwner", text)
        self.assertIn("bj_lastCreatedUnit\t写入\tBJ变量", text)
        self.assertNotIn("udg_Bad", text)
        self.assertNotIn("udg_Fake", text)


if __name__ == "__main__":
    unittest.main()
