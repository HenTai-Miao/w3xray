"""知识包导出脚本函数索引。"""

import os
import tempfile
import unittest

from w3xtool.api import MapData
from w3xtool.knowledge_pack import write_knowledge_pack


class KnowledgePackScriptFunctionIndexTest(unittest.TestCase):
    def test_pack_exports_script_function_index(self):
        # Given: a parsed map with function-scoped save and object-ID logic.
        md = MapData(path="x.w3x", name="函数索引图")
        md.scripts = {
            "war3map.j": "\n".join((
                "function Init takes nothing returns nothing",
                "    call CreateUnit(Player(0), 'H001', 0, 0, 0)",
                "endfunction",
            )),
        }

        # When: the user exports the knowledge pack.
        with tempfile.TemporaryDirectory() as out:
            write_knowledge_pack(md, out)

            # Then: the pack contains function-scoped script investigation rows.
            with open(os.path.join(out, "脚本函数索引.tsv"), encoding="utf-8") as f:
                index = f.read()
            self.assertIn("函数\t来源\t起始行\t结束行\t行数\t被调用次数\t内部调用数\t机制\t对象码\t调用函数\t摘要", index)
            self.assertIn("Init\twar3map.j\t1\t3\t3\t0\t1\tObjectID:单位\tH001", index)

            with open(os.path.join(out, "资料包目录.tsv"), encoding="utf-8") as f:
                manifest = f.read()
            self.assertIn("脚本\t脚本函数索引.tsv\t函数范围、调用关系、机制和对象码", manifest)


if __name__ == "__main__":
    unittest.main()
