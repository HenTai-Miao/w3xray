"""战役(.w3n)完整提取集成测试（用真实战役文件，缺失则 skip）。

战役有三层内容：①顶层 war3campaign.* 共享对象 ②各子图 war3map.* 对象 ③资源文件。
"""
import glob
import os
import shutil
import tempfile
import unittest

from w3xtool.api import load_map, export_all_files

_CAMPAIGN = r"C:\Program Files (x86)\Warcraft III\war3\campaigns\dz\206774.w3n"


@unittest.skipUnless(os.path.exists(_CAMPAIGN), "需要真实战役 206774.w3n")
class TestCampaignExtraction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.md = load_map(_CAMPAIGN)

    def test_has_seven_sub_maps(self):
        self.assertEqual(len(self.md.sub_maps), 7)

    def test_each_submap_has_objects(self):
        for s in self.md.sub_maps:
            self.assertGreater(sum(s.category_counts().values()), 0, f"{s.name} 无对象")

    def test_campaign_level_shared_objects_parsed(self):
        # 顶层 war3campaign.w3u/w3t/... 共享对象应被解析（修复前为 0）
        self.assertGreater(sum(self.md.category_counts().values()), 0,
                           "战役级共享对象(war3campaign.*)未解析")

    def test_submap_resolves_campaign_shared_names(self):
        # 子地图脚本引用的码若在战役共享对象里有定义，应解析出真名而非光秃秃 ID
        shared = self.md.obj_index
        self.assertIn("H600", shared)                 # 战役共享里 H600=法师
        sub = self.md.sub_maps[1]                      # XSHZ-1 引用了 H600
        obj = sub.obj_index.get("H600")
        self.assertIsNotNone(obj, "子地图未收录被引用的共享对象 H600")
        self.assertNotEqual(obj.name, "H600", "H600 仍是光秃秃 ID，未从战役共享对象取名")
        self.assertEqual(obj.name, shared["H600"].name)

    def test_recursive_export_includes_submap_internals(self):
        out = tempfile.mkdtemp(prefix="w3xtest_")
        try:
            export_all_files(_CAMPAIGN, out)
            # 顶层战役共享对象文件
            self.assertTrue(os.path.exists(os.path.join(out, "war3campaign.w3u")))
            # 资源（图标）
            self.assertTrue(glob.glob(os.path.join(out, "*.blp")), "未导出 .blp 资源")
            # 子地图内部被递归导出（关键：不只是 .w3x 整包）
            self.assertTrue(os.path.exists(os.path.join(out, "XSHZ-1", "war3map.j")),
                            "子地图内部未递归导出")
        finally:
            shutil.rmtree(out, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
