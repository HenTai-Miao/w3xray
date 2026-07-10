"""Bounded MPQ block reading independent of archive name-table lookup."""

from __future__ import annotations

import struct
from typing import Final, Protocol

from .explode import explode
from .mpq_compression import decompress_mpq_sector
from .mpq_constants import (
    FLAG_COMPRESS,
    FLAG_ENCRYPTED,
    FLAG_FIX_KEY,
    FLAG_IMPLODE,
    FLAG_SECTOR_CRC,
    FLAG_SINGLE_UNIT,
    HASH_FILE_KEY,
)
from .mpq_crypto import _decrypt, _detect_offtable_key, hash_name_bytes
from .mpq_layout import ArchiveBytes, _Block


DERIVE_KEY: Final = -1
BLOCK_RECOVERY_ERRORS: Final = (KeyError, ValueError, struct.error)


class MPQBlockError(ValueError):
    """Raised when an MPQ block violates structural bounds."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class MPQBlockStorage(Protocol):
    """Archive state required by the block reader."""

    _data: ArchiveBytes
    archive_offset: int
    sector_size: int


def parse_sector_offsets(raw: bytes, count: int, key: int | None) -> list[int]:
    """Parse a decrypted, monotonic sector-offset table bounded by ``raw``."""
    need = count * 4
    if count < 1 or len(raw) < need:
        raise MPQBlockError("扇区偏移表损坏：偏移表被截断")
    table = raw[:need]
    if key is not None:
        table = _decrypt(table, key)
    offsets = list(struct.unpack(f"<{count}I", table))
    if offsets[0] < need or offsets[0] > len(raw):
        raise MPQBlockError("扇区偏移表损坏：首偏移位于表内或越界")
    for current, following in zip(offsets, offsets[1:]):
        if current > following or following > len(raw):
            raise MPQBlockError("扇区偏移表损坏：偏移非单调或越界")
    return offsets


def _raw_block(storage: MPQBlockStorage, block: _Block, name_bytes: bytes) -> bytes:
    start = storage.archive_offset + block.file_pos
    end = start + block.comp_size
    if start < 0 or start > len(storage._data):
        raise KeyError(name_bytes)
    if end < start or end > len(storage._data):
        raise MPQBlockError("MPQ block data is truncated")
    return bytes(storage._data[start:end])


def _resolve_key(block: _Block, name_bytes: bytes, key: int | None) -> int | None:
    if key != DERIVE_KEY:
        return key
    if not block.flags & FLAG_ENCRYPTED:
        return None
    base_name = name_bytes.replace(b"/", b"\\").rsplit(b"\\", 1)[-1]
    resolved = hash_name_bytes(base_name, HASH_FILE_KEY)
    if block.flags & FLAG_FIX_KEY:
        resolved = ((resolved + block.file_pos) ^ block.file_size) & 0xFFFFFFFF
    return resolved


def decompress_mpq_block(data: bytes, output_size: int, flags: int) -> bytes:
    """Decode a block or sector according to its MPQ file flags."""
    if flags & FLAG_IMPLODE and not flags & FLAG_COMPRESS:
        return explode(data, max_output=output_size)
    return decompress_mpq_sector(data, output_size)


def _read_uncompressed(
    storage: MPQBlockStorage, block: _Block, raw: bytes, key: int | None
) -> bytes:
    if key is None:
        return raw[: block.file_size]
    out = bytearray()
    sector_count = (block.file_size + storage.sector_size - 1) // storage.sector_size
    for index in range(sector_count):
        remaining = block.file_size - index * storage.sector_size
        start = index * storage.sector_size
        segment = raw[start : start + min(storage.sector_size, remaining)]
        out.extend(_decrypt(segment, (key + index) & 0xFFFFFFFF))
    return bytes(out[: block.file_size])


def _read_sectors(
    storage: MPQBlockStorage, block: _Block, raw: bytes, key: int | None
) -> bytes:
    sector_count = (block.file_size + storage.sector_size - 1) // storage.sector_size
    offset_count = sector_count + 1 + bool(block.flags & FLAG_SECTOR_CRC)
    offset_key = (key - 1) & 0xFFFFFFFF if key is not None else None
    offsets = parse_sector_offsets(raw, offset_count, offset_key)
    out = bytearray()
    for index in range(sector_count):
        sector = raw[offsets[index] : offsets[index + 1]]
        if key is not None:
            sector = _decrypt(sector, (key + index) & 0xFFFFFFFF)
        expected = min(
            storage.sector_size, block.file_size - index * storage.sector_size
        )
        if len(sector) < expected:
            sector = decompress_mpq_block(sector, expected, block.flags)
        out.extend(sector)
    return bytes(out[: block.file_size])


def read_mpq_block(
    storage: MPQBlockStorage,
    block: _Block,
    name_bytes: bytes,
    key: int | None,
) -> bytes:
    """Read one named or anonymous MPQ block with encryption and sector handling."""
    raw = _raw_block(storage, block, name_bytes)
    resolved_key = _resolve_key(block, name_bytes, key)
    compressed = bool(block.flags & (FLAG_COMPRESS | FLAG_IMPLODE))
    if block.flags & FLAG_SINGLE_UNIT:
        buffer = _decrypt(raw, resolved_key) if resolved_key is not None else raw
        if compressed and block.comp_size < block.file_size:
            buffer = decompress_mpq_block(buffer, block.file_size, block.flags)
        return buffer[: block.file_size]
    if not compressed:
        return _read_uncompressed(storage, block, raw, resolved_key)
    return _read_sectors(storage, block, raw, resolved_key)


def recover_mpq_block_key(storage: MPQBlockStorage, block: _Block) -> int | None:
    """Recover an anonymous encrypted block key from known sector offsets."""
    flags = block.flags
    if not flags & FLAG_ENCRYPTED or flags & FLAG_SINGLE_UNIT:
        return None
    if not flags & (FLAG_COMPRESS | FLAG_IMPLODE):
        return None
    raw = _raw_block(storage, block, b"")
    if len(raw) < 8:
        return None
    encrypted_first, encrypted_second = struct.unpack_from("<II", raw)
    sector_count = (block.file_size + storage.sector_size - 1) // storage.sector_size
    for has_crc in (0, 1):
        offset_count = sector_count + 1 + has_crc
        table_key = _detect_offtable_key(
            encrypted_first, encrypted_second, offset_count * 4, len(raw)
        )
        if table_key is None:
            continue
        try:
            parse_sector_offsets(raw, offset_count, table_key)
        except ValueError:
            continue
        return (table_key + 1) & 0xFFFFFFFF
    return None


def decompress_unencrypted_block(
    storage: MPQBlockStorage, block: _Block
) -> bytes | None:
    """Compatibility recovery helper that skips encrypted blocks."""
    if block.flags & FLAG_ENCRYPTED:
        return None
    try:
        return read_mpq_block(storage, block, b"", DERIVE_KEY)
    except BLOCK_RECOVERY_ERRORS:
        return None


def read_mpq_block_anonymous(
    storage: MPQBlockStorage, block: _Block
) -> bytes | None:
    """Read a block without a filename, recovering its key when possible."""
    try:
        if block.flags & FLAG_ENCRYPTED:
            key = recover_mpq_block_key(storage, block)
            if key is None:
                return None
            return read_mpq_block(storage, block, b"", key)
        return read_mpq_block(storage, block, b"", DERIVE_KEY)
    except BLOCK_RECOVERY_ERRORS:
        return None


def peek_mpq_block(storage: MPQBlockStorage, block: _Block, size: int = 64) -> bytes:
    """Decode only the first unencrypted sector for format probing."""
    if block.flags & FLAG_ENCRYPTED or size <= 0:
        return b""
    try:
        raw = _raw_block(storage, block, b"")
        compressed = bool(block.flags & (FLAG_COMPRESS | FLAG_IMPLODE))
        if block.flags & FLAG_SINGLE_UNIT:
            if compressed and block.comp_size < block.file_size:
                raw = decompress_mpq_block(raw, block.file_size, block.flags)
            return raw[:size]
        sector_count = (block.file_size + storage.sector_size - 1) // storage.sector_size
        offset_count = sector_count + 1 + bool(block.flags & FLAG_SECTOR_CRC)
        offsets = parse_sector_offsets(raw, offset_count, None)
        sector = raw[offsets[0] : offsets[1]]
        expected = min(storage.sector_size, block.file_size)
        if compressed and len(sector) < expected:
            sector = decompress_mpq_block(sector, expected, block.flags)
        return sector[:size]
    except BLOCK_RECOVERY_ERRORS:
        return b""
