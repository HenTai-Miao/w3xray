"""脚本全局变量索引：整理 JASS globals 块中的变量线索。"""

import importlib
import importlib.util
import unittest

from w3xtool.api import MapData


def _format_globals(md: MapData) -> str:
    spec = importlib.util.find_spec("w3xtool.script_global_index")
    if spec is None:
        raise AssertionError("w3xtool.script_global_index module is missing")
    module = importlib.import_module("w3xtool.script_global_index")
    index = module.build_script_global_index(md)
    return module.format_script_global_index_tsv(index)


class ScriptGlobalIndexTest(unittest.TestCase):
    def test_indexes_jass_globals_with_values_codes_and_purpose(self):
        # Given: JASS globals include object IDs, save keys, arrays and switches.
        md = MapData(path="x.w3x", name="全局变量图")
        md.scripts = {
            "war3map.j": "\n".join((
                "globals",
                "    constant integer HERO_ID = 'H001'",
                '    string SAVE_KEY = "hero.level"',
                "    integer array PlayerGold",
                "    boolean DebugMode = true",
                '    string IconPath = "ReplaceableTextures\\\\CommandButtons\\\\BTNHero.blp"',
                "endglobals",
            )),
        }

        # When: the globals index is built.
        text = _format_globals(md)

        # Then: each global keeps source line, shape, initial value and static purpose.
        self.assertIn("来源\t行号\t名称\t类型\t数组\t常量\t初值\t字符串\t对象码\t用途\t摘要", text)
        self.assertIn("war3map.j\t2\tHERO_ID\tinteger\t否\t是\t'H001'\t\tH001\t对象码", text)
        self.assertIn("war3map.j\t3\tSAVE_KEY\tstring\t否\t否\t\"hero.level\"\thero.level\t\t存档/键", text)
        self.assertIn("war3map.j\t4\tPlayerGold\tinteger\t是\t否\t\t\t\t数组状态", text)
        self.assertIn("war3map.j\t5\tDebugMode\tboolean\t否\t否\ttrue\t\t\t开关", text)
        self.assertIn("war3map.j\t6\tIconPath\tstring\t否\t否", text)
        self.assertIn("资源路径", text)

    def test_ignores_comments_and_non_global_locals(self):
        # Given: comments and function locals look like globals but are not in a globals block.
        md = MapData(path="x.w3x", name="去噪全局变量图")
        md.scripts = {
            "war3map.j": "\n".join((
                "// globals",
                '// string BAD = "comment"',
                "globals",
                '    string Real = "yes" // string Comment = "no"',
                "endglobals",
                "function Init takes nothing returns nothing",
                "    local integer NotGlobal = 'H999'",
                "endfunction",
            )),
        }

        # When: the globals index is built.
        text = _format_globals(md)

        # Then: only real declarations inside globals/endglobals are indexed.
        self.assertIn("Real\tstring", text)
        self.assertIn("yes", text)
        self.assertNotIn("BAD", text)
        self.assertNotIn("comment", text)
        self.assertNotIn("NotGlobal", text)
        self.assertNotIn("H999", text)


if __name__ == "__main__":
    unittest.main()
