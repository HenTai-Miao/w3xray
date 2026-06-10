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


def _write_chunks(chunks, total_size):
    buf = bytearray(total_size)
    for off, b in chunks:
        buf[off:off + len(b)] = b
    fd, path = tempfile.mkstemp(suffix=".w3x")
    os.close(fd)
    with open(path, "wb") as f:
        f.write(buf)
    return path


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

    def test_block_table_past_eof_tolerated(self):
        # 保护图常见手法：block 表声明的长度超出文件尾（block_count 注水）。
        # StormLib 只读实际存在的条目即可加载，我们也应容忍：hash 表完整、
        # block 表起点在文件内 → 不拒绝（截断的尾部由 _read_tables 自然丢弃）。
        # hash: pos=32 count=4 → 占 32..96；block: pos=96 count=4 → 声明 96..160；
        # 文件只有 112 字节 → block 表尾越界 32 字节，但起点(96)在文件内。
        path = _write_mpq(_hdr(4, 4, hash_pos=32, block_pos=96), 112)
        try:
            a = MPQArchive(path)                       # 不应抛异常
            self.assertEqual(a.archive_offset, 0)
            self.assertLessEqual(len(a.block_table), 4)  # 只读到实际存在的条目
        finally:
            os.remove(path)


class TestDecoyHeader(unittest.TestCase):
    def test_skips_decoy_header_and_finds_real(self):
        # 头部混淆图（如 _w3p 打包）：在 512 处放一个非法的诱饵 MPQ 头，
        # 真头挪到 1024。扫描应跳过校验不过的诱饵，定位到真头。
        decoy = _hdr(1000, 1)                          # hash_count 非 2 的幂 → 非法
        real = _hdr(4, 1, hash_pos=32, block_pos=96)   # 合法，表都在文件内
        path = _write_chunks([(512, decoy), (1024, real)], 4096)
        try:
            a = MPQArchive(path)
            self.assertEqual(a.archive_offset, 1024)
        finally:
            os.remove(path)

    def test_no_valid_header_still_raises(self):
        # 全是非法头时仍应报错，而不是静默通过
        decoy = _hdr(1000, 1)
        path = _write_chunks([(512, decoy), (1024, _hdr(777, 1))], 4096)
        try:
            with self.assertRaises(ValueError):
                MPQArchive(path)
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
