"""MPQ 读取对不可信/损坏文件的健壮性：

- 扇区偏移表必须单调且在数据内，否则抛清晰 ValueError（而非静默产出错误字节）。
- block 指向文件外时应报错（而非静默返回空数据）。
"""

import mmap
import os
import struct
import tempfile
import bz2
import zlib
import unittest
from pathlib import Path

import pytest

from gametool import mpq_storage
from gametool.mpq import (
    FLAG_COMPRESS,
    FLAG_ENCRYPTED,
    MPQArchive,
    _Block,
    _decrypt,
    _parse_sector_offsets,
    FLAG_EXISTS,
    FLAG_SINGLE_UNIT,
)


def _write_min_mpq():
    """写一张最小可解析的 MPQ：hash 表 4 项、block 表 1 项，都在文件内。"""
    hdr = struct.pack("<4sIIHHIIII", b"MPQ\x1a", 0x20, 0, 0, 3, 32, 96, 4, 1)
    buf = bytearray(112)
    buf[0 : len(hdr)] = hdr
    fd, path = tempfile.mkstemp(suffix=".w3x")
    os.close(fd)
    with open(path, "wb") as f:
        f.write(buf)
    return path


def test_constructor_failure_closes_real_mmap_and_handle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "large-invalid.w3x"
    with path.open("wb") as handle:
        handle.truncate(41 * 1024 * 1024)
    real_mmap = mmap.mmap
    real_open = mpq_storage.open_regular_binary
    mapped_objects: list[mmap.mmap] = []
    source_handles = []

    def tracking_mmap(*args, **kwargs):
        mapped = real_mmap(*args, **kwargs)
        mapped_objects.append(mapped)
        return mapped

    def tracking_open(file: str):
        handle, size = real_open(file)
        if Path(file) == path:
            source_handles.append(handle)
        return handle, size

    monkeypatch.setattr(mmap, "mmap", tracking_mmap)
    monkeypatch.setattr(mpq_storage, "open_regular_binary", tracking_open)

    with pytest.raises(ValueError, match="没找到 MPQ 头"):
        MPQArchive(str(path))

    assert len(mapped_objects) == 1 and mapped_objects[0].closed
    assert len(source_handles) == 1 and source_handles[0].closed


@pytest.mark.parametrize("single_unit", (False, True))
@pytest.mark.parametrize("codec", ("zlib", "bzip2"))
def test_block_read_rejects_decoded_overrun_without_publishing_truncated_prefix(
    single_unit: bool, codec: str
) -> None:
    actual = b"x" * 128
    compressed = (
        b"\x02" + zlib.compress(actual)
        if codec == "zlib"
        else b"\x10" + bz2.compress(actual)
    )
    raw = (
        compressed
        if single_unit
        else struct.pack("<II", 8, 8 + len(compressed)) + compressed
    )
    archive = object.__new__(MPQArchive)
    archive._data = raw
    archive.archive_offset = 0
    archive.sector_size = 4096
    block = _Block(
        0,
        len(raw),
        64,
        FLAG_EXISTS | FLAG_COMPRESS | (FLAG_SINGLE_UNIT if single_unit else 0),
    )

    with pytest.raises(ValueError, match="decoded size"):
        archive._read_block(block, "overrun.txt")
    assert archive.read_block_anon(block) is None


class TestSectorOffsets(unittest.TestCase):
    def test_valid_offsets_pass(self):
        raw = struct.pack("<3I", 12, 16, 20) + b"x" * 8  # len(raw)=20
        self.assertEqual(_parse_sector_offsets(raw, 3, None), [12, 16, 20])

    def test_non_monotonic_rejected(self):
        raw = struct.pack("<3I", 12, 8, 20) + b"x" * 20  # 12 > 8 非单调
        with self.assertRaises(ValueError):
            _parse_sector_offsets(raw, 3, None)

    def test_offset_past_data_rejected(self):
        raw = struct.pack("<3I", 12, 16, 9999) + b"x" * 8  # 9999 > len(raw)
        with self.assertRaises(ValueError):
            _parse_sector_offsets(raw, 3, None)

    def test_truncated_table_rejected(self):
        raw = b"\x00\x00"  # 不足 count*4
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

    def test_peek_uncompressed_sector_storage_keeps_payload_prefix(self):
        payload = b"[H001]\r\nName=Confirmed\r\n" * 300
        a = self._bare_archive(payload)
        blk = _Block(
            file_pos=0,
            comp_size=len(payload),
            file_size=len(payload),
            flags=FLAG_EXISTS,
        )

        self.assertEqual(a._read_block(blk, "objects.txt"), payload)
        self.assertEqual(a.peek_block(blk, 8192), payload[:8192])

    def test_peek_uncompressed_storage_does_not_include_padding(self):
        a = self._bare_archive(b"data-padding")
        blk = _Block(file_pos=0, comp_size=12, file_size=4, flags=FLAG_EXISTS)

        self.assertEqual(a.peek_block(blk, 64), b"data")

    def test_peek_empty_compressed_storage_returns_empty_prefix(self):
        a = self._bare_archive(struct.pack("<I", 4))
        blk = _Block(
            file_pos=0, comp_size=4, file_size=0, flags=FLAG_EXISTS | FLAG_COMPRESS
        )

        self.assertEqual(a._read_block(blk, "empty.txt"), b"")
        self.assertEqual(a.peek_block(blk, 64), b"")


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

        assert isinstance(key, int)
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
            a.close()  # 再次关闭不应抛异常
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
