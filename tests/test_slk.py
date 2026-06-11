"""SLK 解析测试：单元格定位（含 F 记录设置光标后 C 记录沿用位置）。"""
import unittest

from w3xtool.slk import parse_slk


class TestParseSlk(unittest.TestCase):
    def test_basic_cells_with_explicit_xy(self):
        slk = ('ID\n'
               'C;Y1;X1;K"k"\n'
               'C;Y1;X2;K"name"\n'
               'C;Y2;X1;K"u01"\n'
               'C;Y2;X2;K"勇士"\n'
               'E\n')
        rows = parse_slk(slk)
        self.assertEqual(rows["u01"]["name"], "勇士")

    def test_f_record_sets_cursor_for_following_c(self):
        # F 记录设置光标位置；随后省略 X/Y 的 C 记录应沿用该位置，而非上一个 C 的位置
        slk = ('ID\n'
               'C;Y1;X1;K"k"\n'
               'C;Y1;X2;K"name"\n'
               'C;Y2;X1;K"u01"\n'
               'F;Y2;X2\n'          # 移动光标到 (2,2)
               'C;K"勇士"\n'         # 省略 X/Y → 应写到 (2,2)
               'E\n')
        rows = parse_slk(slk)
        self.assertEqual(rows["u01"]["name"], "勇士")


if __name__ == "__main__":
    unittest.main()
