"""脚本局部变量索引：整理函数内 local 声明的静态线索。"""

import importlib
import importlib.util
import unittest

from w3xtool.api import MapData


def _format_locals(md: MapData) -> str:
    spec = importlib.util.find_spec("w3xtool.script_local_index")
    if spec is None:
        raise AssertionError("w3xtool.script_local_index module is missing")
    module = importlib.import_module("w3xtool.script_local_index")
    index = module.build_script_local_index(md)
    return module.format_script_local_index_tsv(index)


class ScriptLocalIndexTest(unittest.TestCase):
    def test_indexes_jass_locals_with_object_save_and_boolean_clues(self):
        # Given: JASS locals declare object IDs, save keys and flags.
        md = MapData(path="x.w3x", name="局部变量图")
        md.scripts = {
            "war3map.j": "\n".join((
                "function SetupHero takes nothing returns nothing",
                "    local integer heroId = 'H001'",
                "    local string saveKey = \"hero.level\"",
                "    local boolean enabled = true",
                "    call BJDebugMsg(\"local integer fakeId = 'H002'\")",
                "endfunction",
            )),
        }

        # When: the local index is built.
        text = _format_locals(md)

        # Then: executable local declarations keep function context and clues.
        self.assertIn("来源\t行号\t函数\t名称\t类型\t初值\t字符串\t对象码\t用途\t摘要", text)
        self.assertIn("war3map.j\t2\tSetupHero\theroId\tinteger\t'H001'\t\tH001\t对象码", text)
        self.assertIn(
            "war3map.j\t3\tSetupHero\tsaveKey\tstring\t\"hero.level\"\thero.level\t\t存档/键",
            text,
        )
        self.assertIn("war3map.j\t4\tSetupHero\tenabled\tboolean\ttrue\t\t\t开关", text)
        self.assertNotIn("H002", text)

    def test_indexes_lua_locals_and_ignores_comments_and_strings(self):
        # Given: Lua locals include FourCC and resource-path values.
        md = MapData(path="x.w3x", name="Lua 局部变量图")
        md.scripts = {
            "war3map.lua": "\n".join((
                "function setup()",
                "    -- local ignored = FourCC(\"A003\")",
                "    BJDebugMsg(\"local fake = FourCC(\\\"A002\\\")\")",
                "    local abilityId = FourCC(\"A001\")",
                "    local path = \"ui\\\\panel.fdf\"",
                "end",
            )),
        }

        # When: the local index is built.
        text = _format_locals(md)

        # Then: only executable Lua locals are indexed.
        self.assertIn("war3map.lua\t4\tsetup\tabilityId\t\tFourCC(\"A001\")\t\tA001\t对象码", text)
        self.assertIn(
            "war3map.lua\t5\tsetup\tpath\t\t\"ui\\\\panel.fdf\"\tui\\panel.fdf\t\t资源路径",
            text,
        )
        self.assertNotIn("A002", text)
        self.assertNotIn("A003", text)


if __name__ == "__main__":
    unittest.main()
