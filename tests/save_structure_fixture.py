"""Independent encoders for documented save/cache test records (never executed maps)."""

from __future__ import annotations

import struct
import zlib


def u32(value: int) -> bytes:
    return struct.pack("<I", value)


def rawcode(value: str) -> bytes:
    return u32(int.from_bytes(value.encode("latin-1"), "big"))


def cache_bytes(
    tables: tuple[tuple[tuple[str, bytes], ...], ...],
    *,
    cache: str = "Profile.w3v",
    category: str = "hero",
    counts: tuple[int, ...] | None = None,
) -> bytes:
    prefix = u32(0x01020304) + u32(1) + cache.encode() + b"\0" + u32(17) + u32(1)
    prefix += category.encode() + b"\0" + bytes(range(20))
    for index, table in enumerate(tables):
        prefix += u32(len(table) if counts is None else counts[index])
        prefix += b"".join(key.encode() + b"\0" + value for key, value in table)
    return prefix


def hero_bytes(
    layout: str, *, slots: int = 1, skills: int = 1, extensions: int = 1
) -> bytes:
    value = rawcode("H001") + u32(slots)
    value += (rawcode("I001") + u32(7) + u32(0xAABBCCDD)) * slots
    value += struct.pack("<5I", 23456, 7, 0, 0x12345678, 31)
    value += struct.pack("<fI3fIf", 1.5, 23, 0.25, -0.5, 2.75, 17, -3.5)
    value += u32(skills)
    for index in range(skills):
        value += rawcode("A001")
        if layout in {"reforged", "modern_skills"}:
            value += rawcode("A002")
        value += u32(100001 + index)
    value += struct.pack(
        "<3fI2if2s", 123.5, -1.25, 1800.0, 0xDEADBEEF, -9, 11, 2.5, b"\xc1\xfe"
    )
    if layout in {"reforged", "classic_extension"}:
        for _ in range(2):
            value += u32(extensions)
            value += struct.pack("<3I", 1, 0xFFFFFFFF, 3) * extensions
    return value


def embedded_cache(raw: bytes) -> bytes:
    name = b"Campaigns.w3v\0"
    return b"espi" + u32(32 + len(name) + len(raw)) + bytes(range(32)) + name + raw


def container_bytes(
    raw: bytes,
    *,
    shape: str = "<III",
    chunks: int = 1,
    crc_header: bool = False,
    header_version: int = 1,
    header_extension: bytes = b"",
) -> bytes:
    parts: list[bytes] = []
    for index in range(0, len(raw), chunks):
        chunk = raw[index : index + chunks]
        compressor = zlib.compressobj(level=1)
        packed = compressor.compress(chunk) + compressor.flush(zlib.Z_SYNC_FLUSH)
        checksum_header = struct.pack(shape, len(packed), len(chunk), 0)
        h_crc = zlib.crc32(checksum_header) & 0xFFFFFFFF
        d_crc = zlib.crc32(packed) & 0xFFFFFFFF
        checksum = (((d_crc >> 16) ^ (d_crc & 0xFFFF)) & 0xFFFF) << 16 | (
            ((h_crc >> 16) ^ (h_crc & 0xFFFF)) & 0xFFFF
        )
        parts.append(struct.pack(shape, len(packed), len(chunk), checksum) + packed)
    fixed_header_size = (64 if header_version == 0 else 68) if crc_header else 48
    header_size = fixed_header_size + len(header_extension)
    header = bytearray(
        b"Warcraft III recorded game\x1a\0"
        + struct.pack(
            "<5I",
            header_size,
            header_size + sum(map(len, parts)),
            header_version if crc_header else 0,
            len(raw),
            len(parts),
        )
    )
    if crc_header:
        if header_version == 0:
            # Primary layout: gowarcraft3/file/w3g/header.go DecodeHeader,
            # v0 reads 64 bytes: u16 reserved/version/build/flags, u32 time/CRC.
            header += struct.pack("<4H2I", 0, 6, 1234, 0, 500, 0)
        else:
            header += bytes(range(16)) + b"\0" * 4
    header += header_extension
    if crc_header:
        struct.pack_into(
            "<I",
            header,
            fixed_header_size - 4,
            zlib.crc32(header[:fixed_header_size]) & 0xFFFFFFFF,
        )
    return bytes(header) + b"".join(parts)
