"""调查导出：地图/对象 ID 索引补充脚本使用来源。"""

import unittest

from w3xtool.api import GameObject, MapData
from w3xtool.doo import Doodad, Unit
from w3xtool.investigation_exports import format_map_object_id_index


class InvestigationExportsTest(unittest.TestCase):
    def test_map_object_id_index_marks_object_usage_and_unknown_script_ids(self):
        # Given: parsed objects plus script/save references to known and unknown IDs.
        md = MapData(path="x.w3x", name="ID图")
        md.objects = {
            "单位": [
                GameObject(
                    category="单位",
                    ext="w3u",
                    obj_id="H001",
                    base_id="Hpal",
                    name="圣骑士",
                    is_custom=True,
                ),
                GameObject(
                    category="单位",
                    ext="w3u",
                    obj_id="H002",
                    base_id="Hfoo",
                    name="未使用单位",
                    is_custom=True,
                ),
            ],
            "技能": [
                GameObject(
                    category="技能",
                    ext="w3a",
                    obj_id="A001",
                    base_id="AHhb",
                    name="治疗术",
                    is_custom=True,
                ),
            ],
        }
        md.scripts = {
            "war3map.j": "\n".join((
                "call CreateUnit(Player(0), 'H001', 0, 0, 0)",
                "call UnitAddAbility(u, 'A001')",
                "call UnitAddAbility(u, 'A999')",
            )),
            "save.j": "call UnitAddAbility(u, 'A001')",
        }

        # When: the ID index is formatted for the knowledge pack.
        index = format_map_object_id_index(md)

        # Then: known objects show usage, unused objects stay explicit, and unknown IDs get rows.
        self.assertIn("对象\t单位\tH001\t1211117617\t圣骑士\tw3u\t脚本引用", index)
        self.assertIn("war3map.j:1:单位", index)
        self.assertIn("对象\t单位\tH002\t1211117618\t未使用单位\tw3u\t对象表", index)
        self.assertIn("对象\t技能\tA001\t1093677105\t治疗术\tw3a\t脚本引用,存档/ID线索", index)
        self.assertIn("save.j:1:技能", index)
        self.assertIn("war3map.j:2:技能", index)
        self.assertIn("脚本引用\t未知\tA999\t1094269241\t\twar3map.j\t脚本引用", index)
        self.assertIn("war3map.j:3:技能", index)
        self.assertIn("未在对象表中解析", index)

    def test_map_object_id_index_marks_preplaced_items_abilities_and_drops(self):
        # Given: object IDs only referenced from preplaced unit inventory, ability and doodad drops.
        md = MapData(path="x.w3x", name="预放置ID图")
        md.objects = {
            "单位": [GameObject("单位", "w3u", "H001", "Hpal", "圣骑士", True)],
            "技能": [GameObject("技能", "w3a", "A001", "AHhb", "治疗术", True)],
            "物品": [GameObject("物品", "w3t", "I001", "ratf", "力量指环", True)],
        }
        md.obj_index = {obj.obj_id: obj for objects in md.objects.values() for obj in objects}
        md.units = [Unit("H001", 0, 0, 0, 0, 0, items=[(0, "I001")], abilities=[("A001", 1, 2)])]
        md.doodads = [Doodad("D001", 0, 0, 0, 0, 0, drops=[("I001", 100)])]

        # When: the ID index is formatted for the knowledge pack.
        index = format_map_object_id_index(md)

        # Then: embedded preplaced IDs are marked as used, not just the unit/doodad type IDs.
        self.assertIn("对象\t单位\tH001\t1211117617\t圣骑士\tw3u\t预放置", index)
        self.assertIn("对象\t技能\tA001\t1093677105\t治疗术\tw3a\t预放置", index)
        self.assertIn("对象\t物品\tI001\t1227894833\t力量指环\tw3t\t预放置", index)


if __name__ == "__main__":
    unittest.main()
