"""脚本函数索引：按函数范围整理调用、对象码和机制。"""

import unittest

import pytest

import w3xtool.script_function_index as script_function_index
from w3xtool.api import MapData
from w3xtool.script_call_catalog import ScriptCall
from w3xtool.script_function_index import (
    build_script_function_index,
    format_script_function_index_tsv,
)


def test_function_index_does_not_rescan_every_call_for_every_function(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: one script contains many functions and calls.
    md = MapData(path="x.w3x", name="大型函数图")
    md.scripts = {
        "war3map.j": "\n".join(
            line
            for index in range(32)
            for line in (
                f"function F{index} takes nothing returns nothing",
                "    call DoThing()",
                "endfunction",
            )
        ),
    }
    inside_checks = 0
    original_inside = script_function_index._inside

    def counted_inside(
        item: script_function_index._FunctionRange,
        call: ScriptCall,
    ) -> bool:
        nonlocal inside_checks
        inside_checks += 1
        return original_inside(item, call)

    monkeypatch.setattr(script_function_index, "_inside", counted_inside)

    # When: function-scoped call evidence is built.
    index = script_function_index.build_script_function_index(md)

    # Then: calls are indexed once instead of rescanned for every function.
    assert len(index.functions) == 32
    assert inside_checks <= 64


class ScriptFunctionIndexTest(unittest.TestCase):
    def test_indexes_jass_functions_with_calls_codes_and_inbound_counts(self):
        # Given: JASS functions call each other and use save/object APIs.
        md = MapData(path="x.w3x", name="函数图")
        md.scripts = {
            "war3map.j": "\n".join(
                (
                    "function SaveHero takes nothing returns nothing",
                    '    call SaveInteger(udg_hash, StringHash("hero"), StringHash("level"), 7)',
                    "    call UnitAddAbility(u, 'A001')",
                    "endfunction",
                    "",
                    "function Init takes nothing returns nothing",
                    "    call CreateUnit(Player(0), 'H001', 0, 0, 0)",
                    "    call SaveHero()",
                    "endfunction",
                )
            ),
        }

        # When: the function index is built.
        index = build_script_function_index(md)
        text = format_script_function_index_tsv(index)

        # Then: each function row contains range, inbound calls, mechanisms and object IDs.
        self.assertIn(
            "函数\t来源\t起始行\t结束行\t行数\t被调用次数\t内部调用数\t机制\t对象码\t调用函数\t摘要",
            text,
        )
        self.assertIn(
            "SaveHero\twar3map.j\t1\t4\t4\t1\t2\tHashtable:写整数; ObjectID:技能\tA001",
            text,
        )
        self.assertIn(
            "Init\twar3map.j\t6\t9\t4\t0\t2\tObjectID:单位\tH001\tCreateUnit; SaveHero",
            text,
        )

    def test_indexes_lua_functions_and_ignores_comments(self):
        # Given: Lua functions include comments and string literals with function-like snippets.
        md = MapData(path="x.w3x", name="Lua函数图")
        md.scripts = {
            "war3map.lua": "\n".join(
                (
                    "local function SaveHero()",
                    "    -- call CreateItem('I999', 0, 0)",
                    '    print("function Fake() call SaveInteger() end")',
                    '    DzAPI_Map_SaveServerValue(Player(0), "hero.level", "7")',
                    "end",
                    "",
                    "function Init()",
                    "    SaveHero()",
                    "end",
                )
            ),
        }

        # When: the function index is built.
        index = build_script_function_index(md)
        text = format_script_function_index_tsv(index)

        # Then: real Lua function bodies are indexed without comment/string false positives.
        self.assertIn(
            "SaveHero\twar3map.lua\t1\t5\t5\t1\t2\tPlatformSave:写服务器值", text
        )
        self.assertIn("Init\twar3map.lua\t7\t9\t3\t0\t1\t普通调用\t\tSaveHero", text)
        self.assertNotIn("Fake", text)
        self.assertNotIn("I999", text)


if __name__ == "__main__":
    unittest.main()
