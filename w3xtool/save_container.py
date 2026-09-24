"""Bounded, read-only decoding of Warcraft III .w3z/.w3v save containers."""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from typing import Final

SAVE_CONTAINER_SIGNATURE: Final = b"Warcraft III recorded game\x1a\x00"
_HEADER_FIXED_BYTES: Final = 48
_BLOCK_HEADER_BYTES: Final = 12
MAX_SAVE_CONTAINER_BLOCKS: Final = 4096
MAX_SAVE_CONTAINER_RAW_BYTES: Final = 128 * 1024 * 1024


class SaveContainerError(ValueError):
    """Raised when a save container violates its documented binary format."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class SaveContainerHeader:
    header_size: int
    file_size: int
    header_version: int
    decompressed_size: int
    block_count: int
    subheader: bytes


@dataclass(frozen=True, slots=True)
class SaveContainerBlock:
    index: int
    offset: int
    compressed_size: int
    original_size: int
    checksum: int
    checksum_ok: bool


@dataclass(frozen=True, slots=True)
class SaveContainerPayload:
    header: SaveContainerHeader
    blocks: tuple[SaveContainerBlock, ...]
    raw: bytes


def looks_like_save_container(payload: bytes) -> bool:
    """Return True when the payload starts with the recorded-save signature."""
    return payload.startswith(SAVE_CONTAINER_SIGNATURE)


def parse_save_container_header(payload: bytes) -> SaveContainerHeader:
    """Parse and bounds-check the fixed recorded-save header."""
    if len(payload) < _HEADER_FIXED_BYTES:
        raise SaveContainerError(
            f"file too small for save header: {len(payload)} bytes"
        )
    if not looks_like_save_container(payload):
        raise SaveContainerError("bad save container signature")
    header_size, file_size, header_version, decompressed_size, block_count = (
        struct.unpack_from("<5I", payload, len(SAVE_CONTAINER_SIGNATURE))
    )
    if header_size < _HEADER_FIXED_BYTES or header_size > len(payload):
        raise SaveContainerError(f"bad header_size: {header_size}")
    if block_count > MAX_SAVE_CONTAINER_BLOCKS:
        raise SaveContainerError(f"block count exceeds limit: {block_count}")
    return SaveContainerHeader(
        header_size=header_size,
        file_size=file_size,
        header_version=header_version,
        decompressed_size=decompressed_size,
        block_count=block_count,
        subheader=bytes(payload[_HEADER_FIXED_BYTES:header_size]),
    )


def unpack_save_container(
    payload: bytes,
    *,
    max_raw_bytes: int = MAX_SAVE_CONTAINER_RAW_BYTES,
) -> SaveContainerPayload:
    """Strictly decode one container: verified checksums, bounded expansion, no writes.

    Every block's declared original size is checked against the remaining raw
    budget before any decompression, mirroring the declared-expansion rule used
    for MPQ members.
    """
    header = parse_save_container_header(payload)
    raw = bytearray()
    blocks: list[SaveContainerBlock] = []
    offset = header.header_size
    for index in range(header.block_count):
        if offset + _BLOCK_HEADER_BYTES > len(payload):
            raise SaveContainerError(f"block {index}: missing block header")
        compressed_size, original_size, checksum = struct.unpack_from(
            "<III", payload, offset
        )
        data_offset = offset + _BLOCK_HEADER_BYTES
        data_end = data_offset + compressed_size
        if data_end > len(payload):
            raise SaveContainerError(
                f"block {index}: compressed payload extends beyond file"
            )
        compressed = payload[data_offset:data_end]
        expected = _block_checksum(compressed, compressed_size, original_size)
        if checksum != expected:
            raise SaveContainerError(
                f"block {index} checksum mismatch: got {checksum:08x}, expected {expected:08x}"
            )
        remaining = max_raw_bytes - len(raw)
        if original_size > remaining:
            raise SaveContainerError(
                f"block {index} declared size {original_size} exceeds raw budget {max_raw_bytes}"
            )
        try:
            decompressor = zlib.decompressobj(wbits=15)
            chunk = decompressor.decompress(compressed, original_size)
        except zlib.error as exc:
            raise SaveContainerError(
                f"block {index} zlib stream is corrupt: {exc}"
            ) from exc
        if len(chunk) != original_size or decompressor.unconsumed_tail:
            raise SaveContainerError(
                f"block {index} decompressed size does not match declared {original_size}"
            )
        raw += chunk
        blocks.append(
            SaveContainerBlock(
                index, offset, compressed_size, original_size, checksum, True
            )
        )
        offset = data_end
    if offset != len(payload):
        raise SaveContainerError(
            f"trailing bytes after blocks: {len(payload) - offset}"
        )
    return SaveContainerPayload(header, tuple(blocks), bytes(raw))


def _fold_crc16(value: int) -> int:
    return ((value >> 16) ^ (value & 0xFFFF)) & 0xFFFF


def _block_checksum(compressed: bytes, compressed_size: int, original_size: int) -> int:
    header = struct.pack("<III", compressed_size, original_size, 0)
    header_fold = _fold_crc16(zlib.crc32(header) & 0xFFFFFFFF)
    data_fold = _fold_crc16(zlib.crc32(compressed) & 0xFFFFFFFF)
    return (data_fold << 16) | header_fold
