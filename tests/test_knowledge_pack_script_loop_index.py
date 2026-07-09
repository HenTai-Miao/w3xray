"""知识包导出脚本循环索引。"""

import os
import tempfile
import unittest

from w3xtool.api import MapData
from w3xtool.knowledge_pack import write_knowledge_pack


class KnowledgePackScriptLoopIndexTest(unittest.TestCase):
    def test_pack_exports_script_loop_index(self):
        # Given: a parsed map with loop-based save logic.
        md = MapData(path="x.w3x", name="循环索引图")
        md.scripts = {
            "war3map.j": "\n".join((
                "function Spawn takes nothing returns nothing",
                "    loop",
                "        exitwhen LoadInteger(udg_hash, StringHash(\"wave\"), StringHash(\"done\")) > 0",
                "    endloop",
                "endfunction",
            )),
        }

        # When: the user exports the knowledge pack.
        with tempfile.TemporaryDirectory() as out:
            write_knowledge_pack(md, out)

            # Then: the pack contains loop rows and advertises the artifact.
            with open(os.path.join(out, "脚本循环索引.tsv"), encoding="utf-8") as f:
                index = f.read()
            self.assertIn("来源\t行号\t函数\t类型\t表达式\t调用\t变量\t字符串\t对象码\t用途\t摘要", index)
            self.assertIn(
                'war3map.j\t3\tSpawn\texitwhen\tLoadInteger(udg_hash, StringHash("wave"), StringHash("done")) > 0',
                index,
            )

            with open(os.path.join(out, "资料包目录.tsv"), encoding="utf-8") as f:
                manifest = f.read()
            self.assertIn("脚本\t脚本循环索引.tsv\t脚本 loop/exitwhen/for/while 循环和退出条件", manifest)


if __name__ == "__main__":
    unittest.main()
