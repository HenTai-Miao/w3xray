"""MPQ 头健壮性：拒绝非法/恶意的表大小，避免 range(hash_count) 跑数十亿次卡死(DoS)。

合法 MPQ 的 hash 表大小是 2 的幂，且 hash/block 表都能放进文件内。
"""
import os
import struct
import tempfile
import unittest

from w3xtool.mpq import MPQArchive


def _write_mpq(hdr_bytes, total_size):
    buf = bytearray(total_size)
    buf[0:len(hdr_bytes)] = hdr_bytes
    fd, path = tempfile.mkstemp(suffix=".w3x")
    os.close(fd)
    with open(path, "wb") as f:
        f.write(buf)
    return path


def _hdr(hash_count, block_count, hash_pos=32, block_pos=32, shift=3):
    return struct.pack("<4sIIHHIIII", b"MPQ\x1a", 0x20, 0, 0, shift,
                       hash_pos, block_pos, hash_count, block_count)


class TestMpqHeader(unittest.TestCase):
    def _expect_reject(self, path):
        try:
            with self.assertRaises(ValueError):
                MPQArchive(path)
        finally:
            os.remove(path)

    def test_hash_count_not_power_of_two_rejected(self):
        # 1000 不是 2 的幂
        path = _write_mpq(_hdr(1000, 1), 1000 * 16 + 64)
        self._expect_reject(path)

    def test_hash_table_overflow_rejected(self):
        # hash_count=2048 合法，但文件太小放不下表
        path = _write_mpq(_hdr(2048, 1), 64)
        self._expect_reject(path)

    def test_absurd_hash_count_rejected_fast(self):
        # 4 billion：修复前会在 range(hash_count) 卡死；修复后应立即拒绝
        path = _write_mpq(_hdr(0xFFFFFFFF, 1), 64)
        self._expect_reject(path)


if __name__ == "__main__":
    unittest.main()
