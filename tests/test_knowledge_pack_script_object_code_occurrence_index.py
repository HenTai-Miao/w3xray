"""知识包导出脚本对象码出现索引。"""

import os
import tempfile
import unittest

from w3xtool.api import GameObject, MapData
from w3xtool.knowledge_pack import write_knowledge_pack


class KnowledgePackScriptObjectCodeOccurrenceIndexTest(unittest.TestCase):
    def test_pack_exports_script_object_code_occurrence_index(self):
        # Given: a parsed map with object IDs referenced in script code.
        md = MapData(path="x.w3x", name="对象码出现索引图")
        md.objects = {
            "单位": [GameObject("单位", "w3u", "H001", "Hpal", "圣骑士", True)],
        }
        md.obj_index = {obj.obj_id: obj for objects in md.objects.values() for obj in objects}
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

            # Then: the pack contains a per-occurrence object-code investigation table.
            with open(os.path.join(out, "脚本对象码出现索引.tsv"), encoding="utf-8") as f:
                index = f.read()
            self.assertIn("来源\t行号\t函数\t对象码\t10进制\t分类\t名称\t对象来源\t上下文\t机制\t摘要", index)
            self.assertIn("war3map.j\t2\tInit\tH001\t1211117617\t单位\t圣骑士\tw3u\tCreateUnit\tObjectID:单位", index)

            with open(os.path.join(out, "资料包目录.tsv"), encoding="utf-8") as f:
                manifest = f.read()
            self.assertIn("脚本\t脚本对象码出现索引.tsv\t脚本对象码逐次出现位置和上下文", manifest)


if __name__ == "__main__":
    unittest.main()
