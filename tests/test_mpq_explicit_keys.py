"""Final MPQ file keys decode every supported block layout directly."""

from __future__ import annotations

import struct

import pytest

from w3xtool.mpq import (
    FLAG_COMPRESS,
    FLAG_ENCRYPTED,
    FLAG_EXISTS,
    FLAG_FIX_KEY,
    FLAG_SINGLE_UNIT,
    MPQArchive,
    _Block,
)
from w3xtool.mpq_crypto import CRYPT_TABLE


def _encrypt(data: bytes, key: int) -> bytes:
    count = len(data) // 4
    values = struct.unpack(f"<{count}I", data[: count * 4])
    encrypted: list[int] = []
    seed1 = key & 0xFFFF_FFFF
    seed2 = 0xEEEE_EEEE
    for value in values:
        seed2 = (seed2 + CRYPT_TABLE[0x400 + (seed1 & 0xFF)]) & 0xFFFF_FFFF
        encrypted.append((value ^ ((seed1 + seed2) & 0xFFFF_FFFF)) & 0xFFFF_FFFF)
        seed1 = (
            ((~seed1 & 0xFFFF_FFFF) << 0x15) + 0x1111_1111 | (seed1 >> 0x0B)
        ) & 0xFFFF_FFFF
        seed2 = (value + seed2 + (seed2 << 5) + 3) & 0xFFFF_FFFF
    return struct.pack(f"<{count}I", *encrypted) + data[count * 4 :]


def _archive(raw: bytes, block: _Block, *, sector_size: int = 8) -> MPQArchive:
    archive = object.__new__(MPQArchive)
    archive._data = raw
    archive.archive_offset = 0
    archive.sector_size = sector_size
    archive.block_table = [block]
    return archive


@pytest.mark.parametrize("extra_flag", (0, FLAG_FIX_KEY))
def test_final_key_decodes_single_unit_without_reapplying_fix_key(extra_flag: int) -> None:
    # Given: the supplied key is already the final FIX_KEY-adjusted value.
    key = 0x89AB_CDEF
    plaintext = b"single-unit-data"
    raw = _encrypt(plaintext, key)
    block = _Block(0, len(raw), len(plaintext), FLAG_EXISTS | FLAG_ENCRYPTED | FLAG_SINGLE_UNIT | extra_flag)

    # When: the block is read by index with that final key.
    decoded = _archive(raw, block).read_block_with_key(0, key)

    # Then: FIX_KEY is not transformed a second time.
    assert decoded == plaintext


def test_final_key_decodes_uncompressed_multi_sector_block() -> None:
    # Given: each uncompressed sector uses the final key plus its sector index.
    key = 0x1234_5678
    plaintext = b"abcdefghABCDEFGH"
    raw = _encrypt(plaintext[:8], key) + _encrypt(plaintext[8:], key + 1)
    block = _Block(0, len(raw), len(plaintext), FLAG_EXISTS | FLAG_ENCRYPTED)

    # When/Then: the public explicit-key boundary decodes both sectors.
    assert _archive(raw, block).read_block_with_key(0, key) == plaintext


def test_final_key_decodes_sector_table_and_compressed_layout() -> None:
    # Given: an encrypted sector table and two stored full-size sectors.
    key = 0x0F8E_E069
    plaintext = b"abcdefghABCDEFGH"
    offsets = struct.pack("<3I", 12, 20, 28)
    raw = (
        _encrypt(offsets, (key - 1) & 0xFFFF_FFFF)
        + _encrypt(plaintext[:8], key)
        + _encrypt(plaintext[8:], key + 1)
    )
    block = _Block(
        0,
        len(raw),
        len(plaintext),
        FLAG_EXISTS | FLAG_ENCRYPTED | FLAG_COMPRESS,
    )

    # When/Then: the table key and sector keys are applied independently.
    assert _archive(raw, block).read_block_with_key(0, key) == plaintext


def test_explicit_key_rejects_out_of_range_block_index() -> None:
    # Given: an empty block table.
    archive = object.__new__(MPQArchive)
    archive.block_table = []

    # When/Then: callers cannot address an absent source block.
    with pytest.raises(KeyError, match="block index"):
        _ = archive.read_block_with_key(3, 0)
