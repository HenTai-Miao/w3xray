"""知识包导出脚本全局变量索引。"""

import os
import tempfile
import unittest

from w3xtool.api import MapData
from w3xtool.knowledge_pack import write_knowledge_pack


class KnowledgePackScriptGlobalIndexTest(unittest.TestCase):
    def test_pack_exports_script_global_index(self):
        # Given: a parsed map with global save and object-ID constants.
        md = MapData(path="x.w3x", name="全局变量索引图")
        md.scripts = {
            "war3map.j": "\n".join((
                "globals",
                "    constant integer HERO_ID = 'H001'",
                '    string SAVE_KEY = "hero.level"',
                "endglobals",
            )),
        }

        # When: the user exports the knowledge pack.
        with tempfile.TemporaryDirectory() as out:
            write_knowledge_pack(md, out)

            # Then: the pack contains a globals investigation table.
            with open(os.path.join(out, "脚本全局变量索引.tsv"), encoding="utf-8") as f:
                index = f.read()
            self.assertIn("来源\t行号\t名称\t类型\t数组\t常量\t初值\t字符串\t对象码\t用途\t摘要", index)
            self.assertIn("war3map.j\t2\tHERO_ID\tinteger\t否\t是\t'H001'\t\tH001\t对象码", index)
            self.assertIn("war3map.j\t3\tSAVE_KEY\tstring\t否\t否\t\"hero.level\"\thero.level\t\t存档/键", index)

            with open(os.path.join(out, "资料包目录.tsv"), encoding="utf-8") as f:
                manifest = f.read()
            self.assertIn("脚本\t脚本全局变量索引.tsv\t脚本 globals 变量、初值和对象码", manifest)


if __name__ == "__main__":
    unittest.main()
