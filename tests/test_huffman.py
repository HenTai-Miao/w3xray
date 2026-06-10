"""验证 MPQ Huffman 解压（压缩掩码 0x01）。

若 腐朽之渊 地图存在，则读取其 war3map.j（用 Huffman 压缩）并断言解出真实 JASS。
地图不存在时跳过，保证无地图的 CI 也能通过。
"""
import os
import random
import unittest

from w3xtool.huffman import huff_decompress
from w3xtool.mpq import MPQArchive

# 可用环境变量指定 Huffman 测试地图；否则用默认本地路径（不存在则跳过该用例）
MAP_PATH = os.environ.get("W3X_HUFFMAN_MAP", r"C:/Users/zhongerbing/Downloads/腐朽之渊 Rpg v1416d.w3x")


class TestHuffmanSafety(unittest.TestCase):
    """无需外部地图的强制覆盖：解压炸弹封顶 + 任意输入不崩不卡死。"""

    def test_output_never_exceeds_cap(self):
        # 小输入也不得解出超过 out_size 的数据（防解压炸弹）
        for n in (0, 5, 16):
            data = bytes([0]) + bytes(n)            # data_type=0(稀疏) + 一堆 0 比特
            out = huff_decompress(data, 10)
            self.assertLessEqual(len(out), 10)

    def test_empty_input_returns_empty(self):
        self.assertEqual(huff_decompress(b"", 100), b"")

    def test_fuzz_random_bytes_bounded_and_no_crash(self):
        rnd = random.Random(20260610)
        for _ in range(300):
            data = bytes(rnd.randrange(256) for _ in range(rnd.randint(0, 40)))
            cap = rnd.randint(0, 200)
            out = huff_decompress(data, cap)           # 不得抛异常 / 不得卡死
            self.assertIsInstance(out, (bytes, bytearray))
            self.assertLessEqual(len(out), cap)        # 始终不超过硬上限


class TestHuffmanRealMap(unittest.TestCase):
    def test_war3map_j_huffman(self):
        if not os.path.exists(MAP_PATH):
            self.skipTest("Huffman 测试地图不存在（设 W3X_HUFFMAN_MAP 指定）：%s" % MAP_PATH)
        a = MPQArchive(MAP_PATH)
        j = a.read_file("war3map.j")
        self.assertGreater(len(j), 1_000_000)
        text = j.decode("utf-8", "replace")
        self.assertIn("function", text)
        self.assertIn("endfunction", text)


if __name__ == "__main__":
    unittest.main()
