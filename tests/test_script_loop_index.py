"""脚本循环索引：整理 loop/exitwhen/for/while 里的静态线索。"""

import importlib
import importlib.util
import unittest

from w3xtool.api import MapData


def _format_loops(md: MapData) -> str:
    spec = importlib.util.find_spec("w3xtool.script_loop_index")
    if spec is None:
        raise AssertionError("w3xtool.script_loop_index module is missing")
    module = importlib.import_module("w3xtool.script_loop_index")
    index = module.build_script_loop_index(md)
    return module.format_script_loop_index_tsv(index)


class ScriptLoopIndexTest(unittest.TestCase):
    def test_indexes_jass_loop_and_exitwhen_with_static_clues(self):
        # Given: a JASS loop exits based on save data.
        md = MapData(path="x.w3x", name="循环图")
        md.scripts = {
            "war3map.j": "\n".join((
                "function Spawn takes nothing returns nothing",
                "    loop",
                "        exitwhen LoadInteger(udg_hash, StringHash(\"wave\"), StringHash(\"done\")) > 0",
                "        call CreateUnit(Player(0), 'hfoo', 0, 0, 0)",
                "    endloop",
                "endfunction",
            )),
        }

        # When: the loop index is built.
        text = _format_loops(md)

        # Then: the loop and its exit condition are indexed with function context.
        self.assertIn("来源\t行号\t函数\t类型\t表达式\t调用\t变量\t字符串\t对象码\t用途\t摘要", text)
        self.assertIn("war3map.j\t2\tSpawn\tloop\t", text)
        self.assertIn(
            'war3map.j\t3\tSpawn\texitwhen\tLoadInteger(udg_hash, StringHash("wave"), StringHash("done")) > 0',
            text,
        )
        self.assertIn("LoadInteger; StringHash\tudg_hash\twave; done\t\t存档循环条件", text)

    def test_indexes_lua_loops_and_ignores_comments_and_strings(self):
        # Given: executable Lua loops and fake loop-looking text in comments/strings.
        md = MapData(path="x.w3x", name="Lua 循环图")
        md.scripts = {
            "war3map.lua": "\n".join((
                "function Tick()",
                "    -- while LoadInteger(udg_hash, 1, 2) do",
                '    BJDebugMsg("for i = 1, 3 do")',
                "    while udg_Count < 10 do",
                "        udg_Count = udg_Count + 1",
                "    end",
                "    for i = 1, 3 do",
                "        UnitAddAbility(udg_Hero, FourCC(\"A001\"))",
                "    end",
                "    repeat",
                "        udg_Done = true",
                "    until GetUnitTypeId(udg_Hero) == 'H001'",
                "end",
            )),
        }

        # When: the loop index is built.
        text = _format_loops(md)

        # Then: executable while/for/repeat/until rows are kept and fake text is ignored.
        self.assertIn("war3map.lua\t4\tTick\twhile\tudg_Count < 10", text)
        self.assertIn("war3map.lua\t7\tTick\tfor\ti = 1, 3", text)
        self.assertIn("war3map.lua\t10\tTick\trepeat\t", text)
        self.assertIn(
            "war3map.lua\t12\tTick\tuntil\tGetUnitTypeId(udg_Hero) == 'H001'",
            text,
        )
        self.assertIn("GetUnitTypeId\tudg_Hero\t\tH001\t对象ID循环条件", text)
        self.assertNotIn("LoadInteger", text)
        self.assertNotIn("for i = 1, 3 do\")", text)


if __name__ == "__main__":
    unittest.main()
