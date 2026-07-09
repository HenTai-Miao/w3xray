"""知识包导出预放置单位、装饰物与掉落表。"""

import os
import tempfile
import unittest

from w3xtool.api import GameObject, MapData
from w3xtool.doo import Doodad, Unit
from w3xtool.knowledge_pack import write_knowledge_pack


class KnowledgePackPreplacedTest(unittest.TestCase):
    def test_pack_exports_preplaced_units_doodads_and_drops(self):
        # Given: a map with parsed preplaced units and doodads.
        md = MapData(path="x.w3x", name="预放置图")
        md.objects = {
            "单位": [
                GameObject("单位", "w3u", "H001", "Hpal", "圣骑士", True),
            ],
            "物品": [
                GameObject("物品", "w3t", "I001", "ratf", "力量指环", True),
            ],
            "技能": [
                GameObject("技能", "w3a", "A001", "AHhb", "治疗术", True),
            ],
            "可破坏物": [
                GameObject("可破坏物", "w3b", "D001", "LTlt", "木桶", True),
            ],
        }
        md.obj_index = {obj.obj_id: obj for objects in md.objects.values() for obj in objects}
        md.units = [
            Unit(
                type_id="H001",
                variation=2,
                x=128.0,
                y=-64.5,
                z=12.0,
                angle=90.0,
                player=1,
                hp=500,
                mana=200,
                gold=75,
                hero_level=3,
                items=[(0, "I001")],
                abilities=[("A001", 1, 2)],
                serial=42,
            )
        ]
        md.doodads = [
            Doodad(
                type_id="D001",
                variation=1,
                x=32.0,
                y=48.0,
                z=0.0,
                angle=180.0,
                scale=(1.0, 1.25, 0.75),
                flags=2,
                life=80,
                drops=[("I001", 100)],
                serial=7,
            )
        ]

        # When: the user exports the consolidated knowledge pack.
        with tempfile.TemporaryDirectory() as out:
            write_knowledge_pack(md, out)

            # Then: preplaced objects are available as spreadsheet-friendly TSVs.
            with open(os.path.join(out, "预放置单位.tsv"), encoding="utf-8") as f:
                units = f.read()
            self.assertIn(
                "序号\t类型ID\t名称\t玩家\tX\tY\tZ\t角度\t生命\t魔法\t金矿\t英雄等级\t物品栏\t技能",
                units,
            )
            self.assertIn(
                "42\tH001\t圣骑士\t1\t128\t-64.5\t12\t90\t500\t200\t75\t3\t0:I001(力量指环)\tA001(治疗术):启用:2",
                units,
            )
            with open(os.path.join(out, "预放置装饰物.tsv"), encoding="utf-8") as f:
                doodads = f.read()
            self.assertIn("序号\t类型ID\t名称\tX\tY\tZ\t角度\t缩放\t状态\t生命\t掉落", doodads)
            self.assertIn("7\tD001\t木桶\t32\t48\t0\t180\t1,1.25,0.75\t2\t80\tI001(力量指环):100%", doodads)


if __name__ == "__main__":
    unittest.main()
