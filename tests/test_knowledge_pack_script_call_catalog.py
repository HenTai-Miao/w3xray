"""知识包导出脚本调用清单。"""

import os
import tempfile
import unittest

from w3xtool.api import MapData
from w3xtool.knowledge_pack import write_knowledge_pack


class KnowledgePackScriptCallCatalogTest(unittest.TestCase):
    def test_pack_exports_script_call_catalog(self):
        # Given: a parsed map with script calls relevant to save and object-ID analysis.
        md = MapData(path="x.w3x", name="调用清单图")
        md.scripts = {
            "war3map.j": "\n".join((
                "call CreateUnit(Player(0), 'H001', 0, 0, 0)",
                'call SaveInteger(udg_hash, StringHash("hero"), StringHash("level"), 7)',
            )),
        }

        # When: the user exports the knowledge pack.
        with tempfile.TemporaryDirectory() as out:
            write_knowledge_pack(md, out)

            # Then: the pack contains a grouped script call list.
            with open(os.path.join(out, "脚本调用清单.tsv"), encoding="utf-8") as f:
                catalog = f.read()
            self.assertIn("函数\t次数\t来源\t行号\t机制\t对象码\t字符串参数\t示例", catalog)
            self.assertIn("CreateUnit\t1\twar3map.j\t1\tObjectID:单位\tH001", catalog)
            self.assertIn("SaveInteger\t1\twar3map.j\t2\tHashtable:写整数\t\thero; level", catalog)

            with open(os.path.join(out, "资料包目录.tsv"), encoding="utf-8") as f:
                manifest = f.read()
            self.assertIn("脚本\t脚本调用清单.tsv\t按函数汇总脚本调用、对象码和字符串参数", manifest)


if __name__ == "__main__":
    unittest.main()
