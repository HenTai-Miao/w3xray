"""知识包导出脚本局部变量索引。"""

import os
import tempfile
import unittest

from w3xtool.api import MapData
from w3xtool.knowledge_pack import write_knowledge_pack


class KnowledgePackScriptLocalIndexTest(unittest.TestCase):
    def test_pack_exports_script_local_index(self):
        # Given: a parsed map with function-local declarations.
        md = MapData(path="x.w3x", name="局部变量索引图")
        md.scripts = {
            "war3map.j": "\n".join((
                "function SetupHero takes nothing returns nothing",
                "    local integer heroId = 'H001'",
                "    local string saveKey = \"hero.level\"",
                "endfunction",
            )),
        }

        # When: the user exports the knowledge pack.
        with tempfile.TemporaryDirectory() as out:
            write_knowledge_pack(md, out)

            # Then: the pack contains local rows and advertises the artifact.
            with open(os.path.join(out, "脚本局部变量索引.tsv"), encoding="utf-8") as f:
                index = f.read()
            self.assertIn("来源\t行号\t函数\t名称\t类型\t初值\t字符串\t对象码\t用途\t摘要", index)
            self.assertIn("war3map.j\t2\tSetupHero\theroId\tinteger\t'H001'\t\tH001\t对象码", index)
            self.assertIn("war3map.j\t3\tSetupHero\tsaveKey\tstring\t\"hero.level\"\thero.level", index)

            with open(os.path.join(out, "资料包目录.tsv"), encoding="utf-8") as f:
                manifest = f.read()
            self.assertIn("脚本\t脚本局部变量索引.tsv\t脚本函数内 local 变量、初值和对象码", manifest)


if __name__ == "__main__":
    unittest.main()
