"""脚本返回值索引：整理 return 里的存档、对象码和状态线索。"""

import importlib
import importlib.util
import unittest

from w3xtool.api import MapData


def _format_returns(md: MapData) -> str:
    spec = importlib.util.find_spec("w3xtool.script_return_index")
    if spec is None:
        raise AssertionError("w3xtool.script_return_index module is missing")
    module = importlib.import_module("w3xtool.script_return_index")
    index = module.build_script_return_index(md)
    return module.format_script_return_index_tsv(index)


class ScriptReturnIndexTest(unittest.TestCase):
    def test_indexes_return_values_with_save_and_object_clues(self):
        # Given: functions return save values, object IDs and state variables.
        md = MapData(path="x.w3x", name="返回值图")
        md.scripts = {
            "war3map.j": "\n".join((
                "function LoadHeroLevel takes nothing returns integer",
                "    return LoadInteger(udg_hash, StringHash(\"hero\"), StringHash(\"level\"))",
                "endfunction",
                "function HeroId takes nothing returns integer",
                "    return 'H001'",
                "endfunction",
                "function HeroState takes nothing returns integer",
                "    return udg_HeroState",
                "endfunction",
            )),
        }

        # When: the return index is built.
        text = _format_returns(md)

        # Then: return expressions keep function context and static clues.
        self.assertIn("来源\t行号\t函数\t表达式\t调用\t变量\t字符串\t对象码\t用途\t摘要", text)
        self.assertIn(
            'war3map.j\t2\tLoadHeroLevel\tLoadInteger(udg_hash, StringHash("hero"), StringHash("level"))',
            text,
        )
        self.assertIn("LoadInteger; StringHash\tudg_hash\thero; level\t\t存档返回值", text)
        self.assertIn("war3map.j\t5\tHeroId\t'H001'\t\t\t\tH001\t对象ID返回值", text)
        self.assertIn("war3map.j\t8\tHeroState\tudg_HeroState\t\tudg_HeroState\t\t\t状态变量返回值", text)

    def test_indexes_lua_returns_and_ignores_comments_and_strings(self):
        # Given: Lua returns and fake return-looking text in comments/strings.
        md = MapData(path="x.w3x", name="Lua 返回值图")
        md.scripts = {
            "war3map.lua": "\n".join((
                "function ability_id()",
                "    -- return LoadInteger(udg_hash, 1, 2)",
                '    BJDebugMsg("return udg_Fake")',
                "    return FourCC(\"A001\")",
                "end",
            )),
        }

        # When: the return index is built.
        text = _format_returns(md)

        # Then: only executable returns are indexed.
        self.assertIn("war3map.lua\t4\tability_id\tFourCC(\"A001\")", text)
        self.assertIn("FourCC\t\t\tA001\t对象ID返回值", text)
        self.assertNotIn("LoadInteger", text)
        self.assertNotIn("udg_Fake", text)


if __name__ == "__main__":
    unittest.main()
