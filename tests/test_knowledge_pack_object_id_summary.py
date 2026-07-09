"""知识包导出对象 ID 使用摘要。"""

import os
import tempfile
import unittest

from w3xtool.api import GameObject, MapData
from w3xtool.knowledge_pack import write_knowledge_pack


class KnowledgePackObjectIdSummaryTest(unittest.TestCase):
    def test_pack_exports_object_id_usage_summary(self):
        # Given: a parsed map with object IDs referenced from script APIs.
        md = MapData(path="x.w3x", name="ID摘要图")
        md.objects = {
            "单位": [GameObject("单位", "w3u", "H001", "Hpal", "圣骑士", True)],
        }
        md.obj_index = {obj.obj_id: obj for objects in md.objects.values() for obj in objects}
        md.scripts = {"war3map.j": "call CreateUnit(Player(0), 'H001', 0, 0, 0)"}

        # When: the user exports the knowledge pack.
        with tempfile.TemporaryDirectory() as out:
            write_knowledge_pack(md, out)

            # Then: the pack contains a per-ID source-count summary.
            with open(os.path.join(out, "对象ID使用摘要.tsv"), encoding="utf-8") as f:
                summary = f.read()
            self.assertIn("ID\t10进制\t分类\t名称\t对象来源\t脚本引用\t存档/ID线索", summary)
            self.assertIn("H001\t1211117617\t单位\t圣骑士\tw3u\t1\t1", summary)


if __name__ == "__main__":
    unittest.main()
