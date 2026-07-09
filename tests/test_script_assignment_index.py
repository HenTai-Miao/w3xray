"""脚本赋值索引：整理变量写入、状态变化和 ID 线索。"""

import importlib
import importlib.util
import unittest

from w3xtool.api import MapData


def _format_assignments(md: MapData) -> str:
    spec = importlib.util.find_spec("w3xtool.script_assignment_index")
    if spec is None:
        raise AssertionError("w3xtool.script_assignment_index module is missing")
    module = importlib.import_module("w3xtool.script_assignment_index")
    index = module.build_script_assignment_index(md)
    return module.format_script_assignment_index_tsv(index)


class ScriptAssignmentIndexTest(unittest.TestCase):
    def test_indexes_jass_assignments_with_function_values_codes_and_purpose(self):
        # Given: JASS assignments update save keys, object IDs, arrays and switches.
        md = MapData(path="x.w3x", name="赋值图")
        md.scripts = {
            "war3map.j": "\n".join((
                "function Init takes nothing returns nothing",
                "    set udg_HeroId = 'H001'",
                '    set udg_SaveKey = "hero.level"',
                "    set udg_PlayerGold[GetPlayerId(p)] = 1000",
                "    set udg_DebugMode = true",
                "endfunction",
            )),
        }

        # When: the assignment index is built.
        text = _format_assignments(md)

        # Then: assignments keep function context, written variable, value and static purpose.
        self.assertIn("来源\t行号\t函数\t变量\t索引\t右值\t字符串\t对象码\t用途\t摘要", text)
        self.assertIn("war3map.j\t2\tInit\tudg_HeroId\t\t'H001'\t\tH001\t对象码", text)
        self.assertIn("war3map.j\t3\tInit\tudg_SaveKey\t\t\"hero.level\"\thero.level\t\t存档/键", text)
        self.assertIn("war3map.j\t4\tInit\tudg_PlayerGold\tGetPlayerId(p)\t1000\t\t\t数组状态", text)
        self.assertIn("war3map.j\t5\tInit\tudg_DebugMode\t\ttrue\t\t\t开关", text)

    def test_ignores_comments_strings_and_globals_initializers(self):
        # Given: comments, display strings and globals declarations include assignment-looking text.
        md = MapData(path="x.w3x", name="去噪赋值图")
        md.scripts = {
            "war3map.j": "\n".join((
                "globals",
                "    integer HERO_ID = 'H001'",
                "endglobals",
                "function Init takes nothing returns nothing",
                '// set udg_Bad = "comment"',
                '    call BJDebugMsg("set udg_Fake = true")',
                '    set udg_Real = "ok"',
                "endfunction",
            )),
        }

        # When: the assignment index is built.
        text = _format_assignments(md)

        # Then: only real assignment statements are indexed.
        self.assertIn("udg_Real", text)
        self.assertIn("ok", text)
        self.assertNotIn("H001", text)
        self.assertNotIn("udg_Bad", text)
        self.assertNotIn("udg_Fake", text)


if __name__ == "__main__":
    unittest.main()
