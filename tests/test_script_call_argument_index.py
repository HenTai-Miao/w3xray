"""脚本调用参数索引：逐次整理调用参数里的存档键、资源和对象码。"""

import importlib
import importlib.util
import unittest

from w3xtool.api import MapData


def _format_arguments(md: MapData) -> str:
    spec = importlib.util.find_spec("w3xtool.script_call_argument_index")
    if spec is None:
        raise AssertionError("w3xtool.script_call_argument_index module is missing")
    module = importlib.import_module("w3xtool.script_call_argument_index")
    index = module.build_script_call_argument_index(md)
    return module.format_script_call_argument_index_tsv(index)


class ScriptCallArgumentIndexTest(unittest.TestCase):
    def test_indexes_call_arguments_with_save_resource_and_object_clues(self):
        # Given: script calls carry save keys, object IDs and resource paths as arguments.
        md = MapData(path="x.w3x", name="调用参数图")
        md.scripts = {
            "war3map.j": "\n".join((
                "function SaveHero takes nothing returns nothing",
                "    call SaveInteger(udg_hash, StringHash(\"hero\"), StringHash(\"level\"), 'H001')",
                "    call BlzLoadTOCFile(\"ui\\\\panel.toc\")",
                "endfunction",
                "function Spawn takes nothing returns nothing",
                "    call CreateUnit(Player(0), 'hfoo', 0, 0, 270)",
                "endfunction",
            )),
        }

        # When: the call argument index is built.
        text = _format_arguments(md)

        # Then: each argument keeps call, function, value and static clues.
        self.assertIn("来源\t行号\t函数\t调用\t参数序号\t参数\t字符串\t对象码\t机制\t用途\t摘要", text)
        self.assertIn(
            'war3map.j\t2\tSaveHero\tSaveInteger\t2\tStringHash("hero")\thero\t\tHashtable:写整数\t存档/键',
            text,
        )
        self.assertIn(
            "war3map.j\t2\tSaveHero\tSaveInteger\t4\t'H001'\t\tH001\tHashtable:写整数\t对象码",
            text,
        )
        self.assertIn(
            "war3map.j\t3\tSaveHero\tBlzLoadTOCFile\t1\t\"ui\\\\panel.toc\"\tui\\panel.toc\t\t普通调用\t资源路径",
            text,
        )
        self.assertIn("war3map.j\t6\tSpawn\tCreateUnit\t2\t'hfoo'\t\thfoo\tObjectID:单位\t对象码", text)

    def test_indexes_lua_calls_and_ignores_comments_strings_and_definitions(self):
        # Given: Lua code has real calls plus call-like text in comments and strings.
        md = MapData(path="x.w3x", name="Lua 调用参数图")
        md.scripts = {
            "war3map.lua": "\n".join((
                "function setup()",
                "    -- UnitAddAbility(u, FourCC(\"A999\"))",
                "    BJDebugMsg(\"UnitAddAbility(u, FourCC(\\\"A998\\\"))\")",
                "    UnitAddAbility(u, FourCC(\"A001\"))",
                "end",
            )),
        }

        # When: the call argument index is built.
        text = _format_arguments(md)

        # Then: only executable calls are indexed, with Lua function context.
        self.assertIn("war3map.lua\t4\tsetup\tUnitAddAbility\t2\tFourCC(\"A001\")\t\tA001\tObjectID:技能\t对象码", text)
        self.assertNotIn("war3map.lua\t3\tsetup\tUnitAddAbility", text)
        self.assertNotIn("A999", text)


if __name__ == "__main__":
    unittest.main()
