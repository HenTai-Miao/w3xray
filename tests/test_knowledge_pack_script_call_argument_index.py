"""知识包导出脚本调用参数索引。"""

import os
import tempfile
import unittest

from w3xtool.api import MapData
from w3xtool.knowledge_pack import write_knowledge_pack


class KnowledgePackScriptCallArgumentIndexTest(unittest.TestCase):
    def test_pack_exports_script_call_argument_index(self):
        # Given: a parsed map with argument-level save and object clues.
        md = MapData(path="x.w3x", name="调用参数索引图")
        md.scripts = {
            "war3map.j": "\n".join((
                "function SaveHero takes nothing returns nothing",
                "    call SaveInteger(udg_hash, StringHash(\"hero\"), StringHash(\"level\"), 'H001')",
                "endfunction",
            )),
        }

        # When: the user exports the knowledge pack.
        with tempfile.TemporaryDirectory() as out:
            write_knowledge_pack(md, out)

            # Then: the pack contains argument rows and advertises the artifact.
            with open(os.path.join(out, "脚本调用参数索引.tsv"), encoding="utf-8") as f:
                index = f.read()
            self.assertIn("来源\t行号\t函数\t调用\t参数序号\t参数\t字符串\t对象码\t机制\t用途\t摘要", index)
            self.assertIn(
                'war3map.j\t2\tSaveHero\tSaveInteger\t2\tStringHash("hero")\thero',
                index,
            )
            self.assertIn("war3map.j\t2\tSaveHero\tSaveInteger\t4\t'H001'\t\tH001", index)

            with open(os.path.join(out, "资料包目录.tsv"), encoding="utf-8") as f:
                manifest = f.read()
            self.assertIn("脚本\t脚本调用参数索引.tsv\t脚本每次调用的参数、存档键、资源和对象码", manifest)


if __name__ == "__main__":
    unittest.main()
