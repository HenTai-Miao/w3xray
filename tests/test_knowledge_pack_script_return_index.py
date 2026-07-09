"""知识包导出脚本返回值索引。"""

import os
import tempfile
import unittest

from w3xtool.api import MapData
from w3xtool.knowledge_pack import write_knowledge_pack


class KnowledgePackScriptReturnIndexTest(unittest.TestCase):
    def test_pack_exports_script_return_index(self):
        # Given: a parsed map with save-returning script logic.
        md = MapData(path="x.w3x", name="返回值索引图")
        md.scripts = {
            "war3map.j": "\n".join((
                "function LoadHeroLevel takes nothing returns integer",
                "    return LoadInteger(udg_hash, StringHash(\"hero\"), StringHash(\"level\"))",
                "endfunction",
            )),
        }

        # When: the user exports the knowledge pack.
        with tempfile.TemporaryDirectory() as out:
            write_knowledge_pack(md, out)

            # Then: the pack contains return rows and advertises the artifact.
            with open(os.path.join(out, "脚本返回值索引.tsv"), encoding="utf-8") as f:
                index = f.read()
            self.assertIn("来源\t行号\t函数\t表达式\t调用\t变量\t字符串\t对象码\t用途\t摘要", index)
            self.assertIn(
                'war3map.j\t2\tLoadHeroLevel\tLoadInteger(udg_hash, StringHash("hero"), StringHash("level"))',
                index,
            )

            with open(os.path.join(out, "资料包目录.tsv"), encoding="utf-8") as f:
                manifest = f.read()
            self.assertIn("脚本\t脚本返回值索引.tsv\t脚本 return 返回的存档、变量和对象码", manifest)


if __name__ == "__main__":
    unittest.main()
