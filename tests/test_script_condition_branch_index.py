"""脚本条件分支索引：整理 if/elseif 条件里的存档、变量和对象码线索。"""

import importlib
import importlib.util
import unittest

from w3xtool.api import MapData


def _format_conditions(md: MapData) -> str:
    spec = importlib.util.find_spec("w3xtool.script_condition_branch_index")
    if spec is None:
        raise AssertionError("w3xtool.script_condition_branch_index module is missing")
    module = importlib.import_module("w3xtool.script_condition_branch_index")
    index = module.build_script_condition_branch_index(md)
    return module.format_script_condition_branch_index_tsv(index)


class ScriptConditionBranchIndexTest(unittest.TestCase):
    def test_indexes_if_and_elseif_conditions_with_static_clues(self):
        # Given: branch conditions read save data, compare object IDs and check state variables.
        md = MapData(path="x.w3x", name="条件分支图")
        md.scripts = {
            "war3map.j": "\n".join((
                "function CheckHero takes nothing returns nothing",
                "    if LoadInteger(udg_hash, StringHash(\"hero\"), StringHash(\"level\")) > 10 then",
                "        call BJDebugMsg(\"high\")",
                "    elseif GetUnitTypeId(udg_Hero) == 'H001' and udg_DebugMode then",
                "        call BJDebugMsg(\"hero\")",
                "    endif",
                "endfunction",
            )),
        }

        # When: the condition branch index is built.
        text = _format_conditions(md)

        # Then: conditions keep function context and static investigation clues.
        self.assertIn("来源\t行号\t函数\t分支\t条件\t调用\t变量\t字符串\t对象码\t用途\t摘要", text)
        self.assertIn(
            'war3map.j\t2\tCheckHero\tif\tLoadInteger(udg_hash, StringHash("hero"), StringHash("level")) > 10',
            text,
        )
        self.assertIn("LoadInteger; StringHash\tudg_hash\thero; level\t\t存档条件", text)
        self.assertIn(
            "war3map.j\t4\tCheckHero\telseif\tGetUnitTypeId(udg_Hero) == 'H001' and udg_DebugMode",
            text,
        )
        self.assertIn("GetUnitTypeId\tudg_Hero; udg_DebugMode\t\tH001\t对象ID条件", text)

    def test_ignores_comments_and_display_strings(self):
        # Given: comments and UI strings contain if-looking snippets.
        md = MapData(path="x.w3x", name="条件去噪图")
        md.scripts = {
            "war3map.j": "\n".join((
                "function Check takes nothing returns nothing",
                "    // if LoadInteger(udg_hash, 1, 2) > 0 then",
                '    call BJDebugMsg("if udg_Fake then")',
                "    if udg_Real then",
                "    endif",
                "endfunction",
            )),
        }

        # When: the condition branch index is built.
        text = _format_conditions(md)

        # Then: only executable branch conditions are indexed.
        self.assertIn("war3map.j\t4\tCheck\tif\tudg_Real\t\tudg_Real", text)
        self.assertNotIn("udg_Fake", text)
        self.assertNotIn("LoadInteger", text)


if __name__ == "__main__":
    unittest.main()
