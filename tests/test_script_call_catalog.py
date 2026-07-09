"""脚本调用清单：按函数汇总脚本里的静态调用、对象码和字符串参数。"""

import unittest

from w3xtool.api import MapData
from w3xtool.script_call_catalog import build_script_call_catalog, format_script_call_catalog_tsv


class ScriptCallCatalogTest(unittest.TestCase):
    def test_groups_real_calls_with_mechanism_codes_and_strings(self):
        # Given: script calls include object creation, save APIs and sync keys.
        md = MapData(path="x.w3x", name="调用图")
        md.scripts = {
            "war3map.j": "\n".join((
                "call CreateUnit(Player(0), 'H001', 0, 0, 270)",
                'call SaveInteger(udg_hash, StringHash("hero"), StringHash("level"), 7)',
                'call BlzSendSyncData("SAVE", I2S(\'A001\'))',
                "call UnitAddAbility(u, FourCC(\"A001\"))",
            )),
        }

        # When: the call catalog is built.
        catalog = build_script_call_catalog(md)
        text = format_script_call_catalog_tsv(catalog)

        # Then: calls are grouped by function with static investigation clues.
        self.assertIn("函数\t次数\t来源\t行号\t机制\t对象码\t字符串参数\t示例", text)
        self.assertIn("CreateUnit\t1\twar3map.j\t1\tObjectID:单位\tH001", text)
        self.assertIn("SaveInteger\t1\twar3map.j\t2\tHashtable:写整数\t\t", text)
        self.assertIn("hero; level", text)
        self.assertIn("BlzSendSyncData\t1\twar3map.j\t3\tSync:同步数据\tA001\tSAVE", text)
        self.assertIn("UnitAddAbility\t1\twar3map.j\t4\tObjectID:技能\tA001", text)

    def test_ignores_function_like_text_inside_comments_and_strings(self):
        # Given: comments and player-facing strings contain call-like snippets.
        md = MapData(path="x.w3x", name="去噪图")
        md.scripts = {
            "war3map.j": "\n".join((
                "// call CreateItem('I999', 0, 0)",
                'call BJDebugMsg("call SaveInteger(udg_hash, StringHash(\\"fake\\"), 1)")',
                "call CreateItem('I001', 0, 0)",
            )),
        }

        # When: the call catalog is built.
        catalog = build_script_call_catalog(md)
        functions = {row.function for row in catalog.rows}

        # Then: only real code calls become grouped call rows.
        self.assertIn("CreateItem", functions)
        self.assertIn("BJDebugMsg", functions)
        self.assertNotIn("SaveInteger", functions)


if __name__ == "__main__":
    unittest.main()
