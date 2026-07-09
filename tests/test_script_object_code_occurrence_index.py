"""脚本对象码出现索引：逐行整理 rawcode 出现位置和上下文。"""

import importlib
import importlib.util
import unittest

from w3xtool.api import GameObject, MapData


def _format_occurrences(md: MapData) -> str:
    spec = importlib.util.find_spec("w3xtool.script_object_code_occurrence_index")
    if spec is None:
        raise AssertionError("w3xtool.script_object_code_occurrence_index module is missing")
    module = importlib.import_module("w3xtool.script_object_code_occurrence_index")
    index = module.build_script_object_code_occurrence_index(md)
    return module.format_script_object_code_occurrence_index_tsv(index)


class ScriptObjectCodeOccurrenceIndexTest(unittest.TestCase):
    def test_indexes_object_codes_with_function_context_and_object_names(self):
        # Given: script logic references known and unknown object IDs in calls and assignments.
        md = MapData(path="x.w3x", name="对象码出现图")
        md.objects = {
            "单位": [GameObject("单位", "w3u", "H001", "Hpal", "圣骑士", True)],
            "技能": [GameObject("技能", "w3a", "A001", "AHhb", "治疗术", True)],
        }
        md.obj_index = {obj.obj_id: obj for objects in md.objects.values() for obj in objects}
        md.scripts = {
            "war3map.j": "\n".join((
                "function Init takes nothing returns nothing",
                "    call CreateUnit(Player(0), 'H001', 0, 0, 0)",
                "    set udg_AbilityId = FourCC(\"A001\")",
                "    call SaveInteger(udg_hash, StringHash(\"hero\"), StringHash(\"ability\"), 'A001')",
                "    call CreateItem('I999', 0, 0)",
                "endfunction",
            )),
        }

        # When: the object-code occurrence index is built.
        text = _format_occurrences(md)

        # Then: every real object code occurrence is listed with readable context.
        self.assertIn("来源\t行号\t函数\t对象码\t10进制\t分类\t名称\t对象来源\t上下文\t机制\t摘要", text)
        self.assertIn("war3map.j\t2\tInit\tH001\t1211117617\t单位\t圣骑士\tw3u\tCreateUnit\tObjectID:单位", text)
        self.assertIn("war3map.j\t3\tInit\tA001\t1093677105\t技能\t治疗术\tw3a\tudg_AbilityId\t赋值", text)
        self.assertIn("war3map.j\t4\tInit\tA001\t1093677105\t技能\t治疗术\tw3a\tSaveInteger\tHashtable:写整数", text)
        self.assertIn("war3map.j\t5\tInit\tI999\t1228486969\t物品\t\t未解析\tCreateItem\tObjectID:物品", text)

    def test_ignores_comments_and_ordinary_display_strings(self):
        # Given: comments and UI strings contain rawcode-like text while a decimal code is real.
        md = MapData(path="x.w3x", name="对象码去噪图")
        md.objects = {
            "技能": [GameObject("技能", "w3a", "A001", "AHhb", "治疗术", True)],
        }
        md.obj_index = {obj.obj_id: obj for objects in md.objects.values() for obj in objects}
        md.scripts = {
            "war3map.j": "\n".join((
                "function Init takes nothing returns nothing",
                "    // call CreateUnit(Player(0), 'H999', 0, 0, 0)",
                '    call BJDebugMsg("CreateUnit(\\\'H888\\\')")',
                "    call UnitAddAbility(u, 1093677105)",
                "endfunction",
            )),
        }

        # When: the object-code occurrence index is built.
        text = _format_occurrences(md)

        # Then: only executable code contributes object-code rows.
        self.assertIn("war3map.j\t4\tInit\tA001\t1093677105\t技能\t治疗术\tw3a\tUnitAddAbility\tObjectID:技能", text)
        self.assertNotIn("H999", text)
        self.assertNotIn("H888", text)


if __name__ == "__main__":
    unittest.main()
