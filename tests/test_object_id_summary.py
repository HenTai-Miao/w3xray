"""对象 ID 使用摘要：按来源统计脚本、存档、对象字段和预放置。"""

import unittest

from w3xtool.api import GameObject, MapData
from w3xtool.doo import Doodad, Unit
from w3xtool.object_id_summary import format_object_id_usage_summary


class ObjectIdSummaryTest(unittest.TestCase):
    def test_summary_counts_usage_sources_per_object_id(self):
        # Given: known objects plus script, save/object API, field and preplaced references.
        md = MapData(path="x.w3x", name="摘要图")
        md.objects = {
            "单位": [GameObject("单位", "w3u", "H001", "Hpal", "圣骑士", True)],
            "技能": [GameObject("技能", "w3a", "A001", "AHhb", "治疗术", True)],
            "物品": [GameObject("物品", "w3t", "I001", "ratf", "力量指环", True)],
            "可破坏物": [GameObject("可破坏物", "w3b", "D001", "LTlt", "木桶", True)],
            "科技": [GameObject("科技", "w3q", "R001", "Rhpm", "未使用科技", True)],
        }
        md.obj_index = {obj.obj_id: obj for objects in md.objects.values() for obj in objects}
        md.referenced_by = {"A001": [("H001", "圣骑士", "技能列表")]}
        md.scripts = {
            "war3map.j": "\n".join((
                "call CreateUnit(Player(0), 'H001', 0, 0, 0)",
                "call UnitAddAbility(u, 'A001')",
                "call CreateItem('I999', 0, 0)",
            )),
        }
        md.units = [
            Unit("H001", 0, 0, 0, 0, 0, items=[(0, "I001")], abilities=[("A001", 1, 2)])
        ]
        md.doodads = [
            Doodad("D001", 0, 0, 0, 0, 0, drops=[("I001", 100)])
        ]

        # When: the object-ID usage summary is formatted.
        summary = format_object_id_usage_summary(md)

        # Then: each source column is counted independently and unknown script IDs remain visible.
        self.assertIn("ID\t10进制\t分类\t名称\t对象来源\t脚本引用\t存档/ID线索\t对象字段引用\t预放置引用\t状态\t详情", summary)
        self.assertIn("H001\t1211117617\t单位\t圣骑士\tw3u\t1\t1\t0\t1\t已解析", summary)
        self.assertIn("A001\t1093677105\t技能\t治疗术\tw3a\t1\t1\t1\t1\t已解析", summary)
        self.assertIn("I001\t1227894833\t物品\t力量指环\tw3t\t0\t0\t0\t2\t已解析", summary)
        self.assertIn("D001\t1144008753\t可破坏物\t木桶\tw3b\t0\t0\t0\t1\t已解析", summary)
        self.assertIn("R001\t1378889777\t科技\t未使用科技\tw3q\t0\t0\t0\t0\t仅对象表", summary)
        self.assertIn("I999\t1228486969\t未知\t\t未解析\t1\t1\t0\t0\t未在对象表中解析", summary)
        self.assertIn("脚本=war3map.j:3:物品", summary)
        self.assertIn("预放置=单位物品栏:0;装饰物掉落", summary)


if __name__ == "__main__":
    unittest.main()
