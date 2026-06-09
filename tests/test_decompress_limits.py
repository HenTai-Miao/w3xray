"""解压上限测试：单个扇区的解压结果不能超过其声明大小 out_size。

恶意地图可以让一个小压缩扇区解出巨量数据（解压炸弹）造成 OOM。
合法地图里扇区正好解出 out_size 字节，所以按 out_size 封顶是安全的防护。
"""
import bz2
import unittest
import zlib

from w3xtool.mpq import _decompress_sector, _sparse_decompress, COMP_ZLIB, COMP_BZIP2, COMP_SPARSE


class TestDecompressLimits(unittest.TestCase):
    def test_zlib_sector_capped_to_out_size(self):
        payload = bytes([COMP_ZLIB]) + zlib.compress(b"A" * 5000)
        out = _decompress_sector(payload, 100)
        self.assertLessEqual(len(out), 100)

    def test_bzip2_sector_capped_to_out_size(self):
        payload = bytes([COMP_BZIP2]) + bz2.compress(b"B" * 5000)
        out = _decompress_sector(payload, 100)
        self.assertLessEqual(len(out), 100)

    def test_sparse_sector_capped_to_out_size(self):
        # 0x00 控制字节 → 每个产 3 个零字节；50 个 → 150 字节，封顶到 30
        payload = bytes([COMP_SPARSE]) + b"\x00" * 50
        out = _decompress_sector(payload, 30)
        self.assertLessEqual(len(out), 30)

    def test_sparse_helper_respects_max_output(self):
        out = _sparse_decompress(b"\x00" * 50, max_output=30)
        self.assertLessEqual(len(out), 30)

    def test_legit_zlib_roundtrip_unaffected(self):
        original = b"hello world " * 10        # 120 字节
        payload = bytes([COMP_ZLIB]) + zlib.compress(original)
        out = _decompress_sector(payload, len(original))
        self.assertEqual(out, original)


if __name__ == "__main__":
    unittest.main()
