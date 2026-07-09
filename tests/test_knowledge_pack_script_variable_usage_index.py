"""知识包导出脚本变量使用索引。"""

import os
import tempfile
import unittest

from w3xtool.api import MapData
from w3xtool.knowledge_pack import write_knowledge_pack


class KnowledgePackScriptVariableUsageIndexTest(unittest.TestCase):
    def test_pack_exports_script_variable_usage_index(self):
        # Given: a parsed map with global variable reads and writes.
        md = MapData(path="x.w3x", name="变量使用索引图")
        md.scripts = {
            "war3map.j": "\n".join((
                "function SaveHero takes nothing returns nothing",
                "    set udg_HeroId = 'H001'",
                "    call SaveInteger(udg_hash, StringHash(udg_SaveKey), StringHash(udg_SaveKey), udg_Level)",
                "endfunction",
            )),
        }

        # When: the user exports the knowledge pack.
        with tempfile.TemporaryDirectory() as out:
            write_knowledge_pack(md, out)

            # Then: the pack contains a variable usage investigation table.
            with open(os.path.join(out, "脚本变量使用索引.tsv"), encoding="utf-8") as f:
                index = f.read()
            self.assertIn("来源\t行号\t函数\t变量\t访问\t类别\t调用\t对象码\t摘要", index)
            self.assertIn("war3map.j\t2\tSaveHero\tudg_HeroId\t写入\t用户全局\t\tH001", index)
            self.assertIn("war3map.j\t3\tSaveHero\tudg_SaveKey\t读取\t用户全局\tSaveInteger\t", index)

            with open(os.path.join(out, "资料包目录.tsv"), encoding="utf-8") as f:
                manifest = f.read()
            self.assertIn("脚本\t脚本变量使用索引.tsv\t脚本 udg_/gg_ 全局变量读写位置", manifest)


if __name__ == "__main__":
    unittest.main()
