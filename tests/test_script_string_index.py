"""脚本字符串索引：按来源、函数和用途整理字符串字面量。"""

import unittest

from w3xtool.api import MapData
from w3xtool.script_string_index import build_script_string_index, format_script_string_index_tsv


class ScriptStringIndexTest(unittest.TestCase):
    def test_indexes_strings_by_usage_function_and_resolved_text(self):
        # Given: script strings cover UI text, commands, resources, sync and platform save keys.
        md = MapData(path="x.w3x", name="字符串图")
        md.scripts = {
            "war3map.wts": "STRING 1\n{\n开始游戏\n}\n",
            "war3map.j": "\n".join((
                "function Init takes nothing returns nothing",
                '    call BJDebugMsg("TRIGSTR_001")',
                '    call TriggerRegisterPlayerChatEvent(gg_trg_Debug, Player(0), "-save", true)',
                '    call BlzLoadTOCFile("UI\\\\FrameDef\\\\Custom.toc")',
                '    call BlzSendSyncData("SAVE", I2S(level))',
                '    call DzAPI_Map_SaveServerValue(Player(0), "hero.level", "25")',
                "endfunction",
            )),
        }

        # When: the string index is built.
        index = build_script_string_index(md)
        text = format_script_string_index_tsv(index)

        # Then: values are grouped with source line, function context and static purpose.
        self.assertIn("来源\t行号\t函数\t调用\t用途\t字符串\t解析文本\t摘要", text)
        self.assertIn("war3map.j\t2\tInit\tBJDebugMsg\tUI文本\tTRIGSTR_001\t开始游戏", text)
        self.assertIn("war3map.j\t3\tInit\tTriggerRegisterPlayerChatEvent\t聊天指令\t'-save\t", text)
        self.assertIn("war3map.j\t4\tInit\tBlzLoadTOCFile\t资源路径\tUI\\FrameDef\\Custom.toc", text)
        self.assertIn("war3map.j\t5\tInit\tBlzSendSyncData\t同步前缀\tSAVE", text)
        self.assertIn("war3map.j\t6\tInit\tDzAPI_Map_SaveServerValue\t存档/键\thero.level", text)

    def test_ignores_comments_and_fourcc_literals(self):
        # Given: comments and JASS rawcodes should not become string rows.
        md = MapData(path="x.w3x", name="去噪字符串图")
        md.scripts = {
            "war3map.j": "\n".join((
                'call BJDebugMsg("real text")',
                '// call BJDebugMsg("comment text")',
                "call CreateUnit(Player(0), 'H001', 0, 0, 0)",
            )),
        }

        # When: the string index is built.
        text = format_script_string_index_tsv(build_script_string_index(md))

        # Then: only real string literals remain.
        self.assertIn("real text", text)
        self.assertNotIn("comment text", text)
        self.assertNotIn("H001", text)


if __name__ == "__main__":
    unittest.main()
