"""知识包导出脚本字符串索引。"""

import os
import tempfile
import unittest

from w3xtool.api import MapData
from w3xtool.knowledge_pack import write_knowledge_pack


class KnowledgePackScriptStringIndexTest(unittest.TestCase):
    def test_pack_exports_script_string_index(self):
        # Given: a parsed map with UI and save-related script strings.
        md = MapData(path="x.w3x", name="字符串索引图")
        md.scripts = {
            "war3map.j": "\n".join((
                "function Init takes nothing returns nothing",
                '    call BlzSendSyncData("SAVE", I2S(level))',
                "endfunction",
            )),
        }

        # When: the user exports the knowledge pack.
        with tempfile.TemporaryDirectory() as out:
            write_knowledge_pack(md, out)

            # Then: the pack contains a string-literal investigation table.
            with open(os.path.join(out, "脚本字符串索引.tsv"), encoding="utf-8") as f:
                index = f.read()
            self.assertIn("来源\t行号\t函数\t调用\t用途\t字符串\t解析文本\t摘要", index)
            self.assertIn("war3map.j\t2\tInit\tBlzSendSyncData\t同步前缀\tSAVE", index)

            with open(os.path.join(out, "资料包目录.tsv"), encoding="utf-8") as f:
                manifest = f.read()
            self.assertIn("脚本\t脚本字符串索引.tsv\t脚本字符串字面量、用途和函数上下文", manifest)


if __name__ == "__main__":
    unittest.main()
