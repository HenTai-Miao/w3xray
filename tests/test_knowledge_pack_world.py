"""知识包导出世界编辑器区域、镜头和声音表。"""

import os
import tempfile
import unittest

from w3xtool.api import MapData
from w3xtool.knowledge_pack import write_knowledge_pack
from w3xtool.w3world import Camera, Region, Sound


class KnowledgePackWorldTest(unittest.TestCase):
    def test_pack_exports_world_editor_metadata_tables(self):
        # Given: parsed world-editor metadata is attached to the map.
        md = MapData(path="x.w3x", name="世界图")
        md.regions = [
            Region(-128.0, -64.0, 128.0, 64.0, "出生区", 7, "RLhr", "Sound\\Rain.wav", (10, 20, 30), 255)
        ]
        md.cameras = [
            Camera(10.0, 20.0, 0.0, 90.0, 304.0, 1650.0, 0.0, 70.0, 5000.0, 100.0, "开场镜头")
        ]
        md.sounds = [
            Sound("导入声", "war3mapImported\\voice.wav", "DefaultEAXON", 16 | 8, 10, 20, 100,
                  1.0, 2, 200.0, 900.0, 1800.0, 0.25, 5, "gg_snd_voice")
        ]

        # When: the knowledge pack is exported.
        with tempfile.TemporaryDirectory() as out:
            write_knowledge_pack(md, out)

            # Then: regions, cameras and sounds are available as standalone TSVs.
            with open(os.path.join(out, "世界区域.tsv"), encoding="utf-8") as f:
                regions = f.read()
            self.assertIn("ID\t名称\t左\t下\t右\t上\t天气\t环境声音\t颜色RGB\tAlpha", regions)
            self.assertIn("7\t出生区\t-128\t-64\t128\t64\tRLhr\tSound\\Rain.wav\t10,20,30\t255", regions)
            with open(os.path.join(out, "世界镜头.tsv"), encoding="utf-8") as f:
                cameras = f.read()
            self.assertIn("名称\t目标X\t目标Y\tZ偏移\t旋转\t攻击角\t距离\t滚转\t视野\t远裁剪\t近裁剪", cameras)
            self.assertIn("开场镜头\t10\t20\t0\t90\t304\t1650\t0\t70\t5000\t100", cameras)
            with open(os.path.join(out, "世界声音.tsv"), encoding="utf-8") as f:
                sounds = f.read()
            self.assertIn("名称\t路径\t变量\tEAX\t循环\t3D\t音乐\t导入", sounds)
            self.assertIn("导入声\twar3mapImported\\voice.wav\tgg_snd_voice\tDefaultEAXON\t否\t否\t是\t是", sounds)


if __name__ == "__main__":
    unittest.main()
