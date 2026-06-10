"""验证 MPQ Huffman 解压（压缩掩码 0x01）。

若 腐朽之渊 地图存在，则读取其 war3map.j（用 Huffman 压缩）并断言解出真实 JASS。
地图不存在时跳过，保证无地图的 CI 也能通过。
"""
import os
import unittest

from w3xtool.mpq import MPQArchive

MAP_PATH = r"C:/Users/zhongerbing/Downloads/腐朽之渊 Rpg v1416d.w3x"


class TestHuffman(unittest.TestCase):
    def test_war3map_j_huffman(self):
        if not os.path.exists(MAP_PATH):
            self.skipTest("Huffman 测试地图不存在：%s" % MAP_PATH)
        a = MPQArchive(MAP_PATH)
        j = a.read_file("war3map.j")
        self.assertGreater(len(j), 1_000_000)
        text = j.decode("utf-8", "replace")
        self.assertIn("function", text)
        self.assertIn("endfunction", text)


if __name__ == "__main__":
    unittest.main()
