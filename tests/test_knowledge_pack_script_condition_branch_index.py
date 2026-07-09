"""知识包导出脚本条件分支索引。"""

import os
import tempfile
import unittest

from w3xtool.api import MapData
from w3xtool.knowledge_pack import write_knowledge_pack


class KnowledgePackScriptConditionBranchIndexTest(unittest.TestCase):
    def test_pack_exports_script_condition_branch_index(self):
        # Given: a parsed map with save/object decisions in script branches.
        md = MapData(path="x.w3x", name="条件分支索引图")
        md.scripts = {
            "war3map.j": "\n".join((
                "function CheckHero takes nothing returns nothing",
                "    if LoadInteger(udg_hash, StringHash(\"hero\"), StringHash(\"level\")) > 10 then",
                "    endif",
                "endfunction",
            )),
        }

        # When: the user exports the knowledge pack.
        with tempfile.TemporaryDirectory() as out:
            write_knowledge_pack(md, out)

            # Then: the pack contains condition branch rows.
            with open(os.path.join(out, "脚本条件分支索引.tsv"), encoding="utf-8") as f:
                index = f.read()
            self.assertIn("来源\t行号\t函数\t分支\t条件\t调用\t变量\t字符串\t对象码\t用途\t摘要", index)
            self.assertIn(
                'war3map.j\t2\tCheckHero\tif\tLoadInteger(udg_hash, StringHash("hero"), StringHash("level")) > 10',
                index,
            )

            with open(os.path.join(out, "资料包目录.tsv"), encoding="utf-8") as f:
                manifest = f.read()
            self.assertIn("脚本\t脚本条件分支索引.tsv\t脚本 if/elseif 条件里的存档、变量和对象码", manifest)


if __name__ == "__main__":
    unittest.main()
