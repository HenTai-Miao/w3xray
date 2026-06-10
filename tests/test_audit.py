"""解析诊断：把'缺斤少两'信号结构化(名字质量/文件存在但0对象/解析告警等)。

纯逻辑(name_quality / diagnose)用合成数据测，audit_map(IO)用真图(有则测)。
"""
import os
import unittest

from w3xtool.api import GameObject, MapData
from w3xtool.audit import diagnose, name_quality


def _obj(cat, ext, oid, name, base=None, custom=False):
    return GameObject(category=cat, ext=ext, obj_id=oid, base_id=base or oid,
                      name=name, is_custom=custom)


class TestNameQuality(unittest.TestCase):
    def test_counts_good_bare_and_mojibake(self):
        objs = [
            _obj("物品", "w3t", "I001", "治疗药水"),     # good
            _obj("物品", "w3t", "I002", "ID:I002"),      # bare
            _obj("物品", "w3t", "I003", "I003"),         # 名==码 → bare
            _obj("物品", "w3t", "I004", ""),             # 空 → bare
            _obj("装饰物", "w3d", "D001", "石��"),  # 含替换符 → mojibake
        ]
        good, bad, moji = name_quality(objs)
        self.assertEqual(good, 2)        # 治疗药水 + 含替换符那条仍算有名(只额外计 moji)
        self.assertEqual(bad, 3)
        self.assertEqual(moji, 1)


class TestDiagnose(unittest.TestCase):
    def test_flags_object_file_present_but_zero_objects(self):
        # archive 里有 war3map.w3u，但'单位'类别为空 → 应标记缺口
        md = MapData(path="x", name="x",
                     objects={"物品": [_obj("物品", "w3t", "I001", "药水")]},
                     scripts={"war3map.j": "function x endfunction"})
        diag = diagnose(md, ["war3map.w3u", "war3map.w3t", "war3map.j"])
        self.assertIn("war3map.w3u", diag.empty_object_files)
        self.assertNotIn("war3map.w3t", diag.empty_object_files)   # w3t 有物品，不算空
        self.assertTrue(any("w3u" in f for f in diag.flags))

    def test_no_flags_when_healthy(self):
        md = MapData(path="x", name="x",
                     objects={"单位": [_obj("单位", "w3u", "h001", "农民")]},
                     scripts={"war3map.j": "function x endfunction"})
        diag = diagnose(md, ["war3map.w3u", "war3map.j"])
        self.assertEqual(diag.empty_object_files, [])
        self.assertEqual(diag.total_objects, 1)

    def test_flags_no_script(self):
        md = MapData(path="x", name="x",
                     objects={"单位": [_obj("单位", "w3u", "h001", "农民")]},
                     scripts={})
        diag = diagnose(md, ["war3map.w3u"])
        self.assertTrue(any("脚本" in f for f in diag.flags))


class TestReportText(unittest.TestCase):
    def test_report_text_includes_key_signals(self):
        from w3xtool.audit import report_text
        md = MapData(path="x", name="测试图",
                     objects={"物品": [_obj("物品", "w3t", "I001", "药水")]},
                     scripts={"war3map.j": "f"})
        diag = diagnose(md, ["war3map.w3u", "war3map.t"])
        txt = report_text(diag)
        self.assertIn("测试图", txt)
        self.assertIn("物品", txt)            # 类别计数
        self.assertIn("war3map.w3u", txt)     # 空对象文件缺口
        self.assertIsInstance(txt, str)


class TestAuditMapReal(unittest.TestCase):
    MAP = r"C:/Users/zhongerbing/Downloads/腐朽之渊 Rpg v1416d.w3x"

    def test_audit_real_map_if_present(self):
        if not os.path.exists(self.MAP):
            self.skipTest("真图不存在，跳过")
        from w3xtool.audit import audit_map
        diag = audit_map(self.MAP)
        self.assertTrue(diag.ok, diag.error)
        self.assertGreater(diag.total_objects, 100)


if __name__ == "__main__":
    unittest.main()
