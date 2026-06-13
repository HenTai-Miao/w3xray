"""脚本对象码抽取：除 'xxxx'/$XX/FourCC 外，还认十进制/0x 十六进制整数形式的码。

借鉴 w3x2lni backend_searchjass：JASS 里 'hpea' 常被写成等值整数 1752196449 或 0x68706561。
阈值 0x41303030('A000') + 全字节可打印 过滤掉伤害/金钱等普通数字。
"""
import unittest

from w3xtool.script_scan import _codes_in, scan_object_refs


class TestCodeExtraction(unittest.TestCase):
    def test_fourcc_literal_still_works(self):
        self.assertIn("hpea", _codes_in("CreateUnit(p, 'hpea', x, y)"))

    def test_decimal_integer_code(self):
        # 1752196449 == 'hpea'
        self.assertIn("hpea", _codes_in("CreateUnit(p, 1752196449, x, y)"))

    def test_hex_integer_code(self):
        # 0x68706561 == 'hpea'
        self.assertIn("hpea", _codes_in("CreateUnit(p, 0x68706561, x, y)"))

    def test_small_integers_ignored(self):
        # 伤害/金钱等小整数不应被当作对象码（低于阈值或非全可打印）
        codes = _codes_in("SetUnitState(u, 100, 2500)")
        self.assertEqual(codes, [])

    def test_non_printable_int_ignored(self):
        # 0x00112233 各字节不全可打印 → 不是码
        self.assertEqual(_codes_in("foo(0x00112233)"), [])

    def test_scan_object_refs_catches_integer_unit_code(self):
        script = "call CreateUnit(Player(0), 1752196449, 0., 0., 270.)"
        refs = scan_object_refs(script)
        self.assertIn("hpea", refs["单位"])


if __name__ == "__main__":
    unittest.main()
