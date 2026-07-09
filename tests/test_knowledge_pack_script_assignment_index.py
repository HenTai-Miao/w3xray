"""知识包导出脚本赋值索引。"""

import os
import tempfile
import unittest

from w3xtool.api import MapData
from w3xtool.knowledge_pack import write_knowledge_pack


class KnowledgePackScriptAssignmentIndexTest(unittest.TestCase):
    def test_pack_exports_script_assignment_index(self):
        # Given: a parsed map with assignment-based save and object-ID state.
        md = MapData(path="x.w3x", name="赋值索引图")
        md.scripts = {
            "war3map.j": "\n".join((
                "function Init takes nothing returns nothing",
                "    set udg_HeroId = 'H001'",
                '    set udg_SaveKey = "hero.level"',
                "endfunction",
            )),
        }

        # When: the user exports the knowledge pack.
        with tempfile.TemporaryDirectory() as out:
            write_knowledge_pack(md, out)

            # Then: the pack contains assignment investigation rows.
            with open(os.path.join(out, "脚本赋值索引.tsv"), encoding="utf-8") as f:
                index = f.read()
            self.assertIn("来源\t行号\t函数\t变量\t索引\t右值\t字符串\t对象码\t用途\t摘要", index)
            self.assertIn("war3map.j\t2\tInit\tudg_HeroId\t\t'H001'\t\tH001\t对象码", index)
            self.assertIn("war3map.j\t3\tInit\tudg_SaveKey\t\t\"hero.level\"\thero.level\t\t存档/键", index)

            with open(os.path.join(out, "资料包目录.tsv"), encoding="utf-8") as f:
                manifest = f.read()
            self.assertIn("脚本\t脚本赋值索引.tsv\t脚本 set 赋值、状态变量和对象码", manifest)


if __name__ == "__main__":
    unittest.main()
