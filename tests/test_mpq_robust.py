"""MPQ 读取对不可信/损坏文件的健壮性：

- 扇区偏移表必须单调且在数据内，否则抛清晰 ValueError（而非静默产出错误字节）。
- block 指向文件外时应报错（而非静默返回空数据）。
"""
import os
import struct
import tempfile
import unittest

from w3xtool.mpq import (
    FLAG_COMPRESS,
    FLAG_ENCRYPTED,
    MPQArchive,
    _Block,
    _decrypt,
    _parse_sector_offsets,
    FLAG_EXISTS,
)


def _write_min_mpq():
    """写一张最小可解析的 MPQ：hash 表 4 项、block 表 1 项，都在文件内。"""
    hdr = struct.pack("<4sIIHHIIII", b"MPQ\x1a", 0x20, 0, 0, 3, 32, 96, 4, 1)
    buf = bytearray(112)
    buf[0:len(hdr)] = hdr
    fd, path = tempfile.mkstemp(suffix=".w3x")
    os.close(fd)
    with open(path, "wb") as f:
        f.write(buf)
    return path


class TestSectorOffsets(unittest.TestCase):
    def test_valid_offsets_pass(self):
        raw = struct.pack("<3I", 12, 16, 20) + b"x" * 8   # len(raw)=20
        self.assertEqual(_parse_sector_offsets(raw, 3, None), [12, 16, 20])

    def test_non_monotonic_rejected(self):
        raw = struct.pack("<3I", 12, 8, 20) + b"x" * 20    # 12 > 8 非单调
        with self.assertRaises(ValueError):
            _parse_sector_offsets(raw, 3, None)

    def test_offset_past_data_rejected(self):
        raw = struct.pack("<3I", 12, 16, 9999) + b"x" * 8  # 9999 > len(raw)
        with self.assertRaises(ValueError):
            _parse_sector_offsets(raw, 3, None)

    def test_truncated_table_rejected(self):
        raw = b"\x00\x00"                                   # 不足 count*4
        with self.assertRaises(ValueError):
            _parse_sector_offsets(raw, 3, None)


class TestBlockBounds(unittest.TestCase):
    def _bare_archive(self, data):
        a = object.__new__(MPQArchive)
        a._data = data
        a.archive_offset = 0
        a.sector_size = 4096
        return a

    def test_block_past_eof_raises(self):
        a = self._bare_archive(b"\x00" * 100)
        blk = _Block(file_pos=10_000, comp_size=10, file_size=10, flags=FLAG_EXISTS)
        with self.assertRaises((KeyError, ValueError)):
            a._read_block(blk, "x")


class TestAnonymousKeyRecovery(unittest.TestCase):
    def test_recovered_sector_offset_must_fit_inside_block(self):
        a = object.__new__(MPQArchive)
        a.archive_offset = 0
        a.sector_size = 4 * 1024 * 1024
        # Real protected-map block header that has two possible first-offset keys.
        # The wrong key decrypts the second offset past comp_size; the right key
        # decrypts it to a valid in-block sector end.
        a._data = bytes.fromhex("9c 51 ec c8 a4 3c cd d3") + b"\x00" * (4897 - 8)
        blk = _Block(
            file_pos=0,
            comp_size=4897,
            file_size=5140,
            flags=FLAG_EXISTS | FLAG_ENCRYPTED | FLAG_COMPRESS,
        )

        key = a.recover_block_key(blk)

        self.assertEqual(key, 0x0F8EE069)
        off_raw = _decrypt(a._data[:8], (key - 1) & 0xFFFFFFFF)
        self.assertEqual(struct.unpack("<2I", off_raw), (8, 4897))


class TestArchiveLifecycle(unittest.TestCase):
    def test_context_manager_returns_self(self):
        path = _write_min_mpq()
        try:
            with MPQArchive(path) as a:
                self.assertIsInstance(a, MPQArchive)
                self.assertEqual(a.archive_offset, 0)
        finally:
            os.remove(path)

    def test_close_is_idempotent(self):
        path = _write_min_mpq()
        try:
            a = MPQArchive(path)
            a.close()
            a.close()   # 再次关闭不应抛异常
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
