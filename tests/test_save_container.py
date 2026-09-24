"""Bounded read-only decoding of .w3z/.w3v recorded-save containers."""

from __future__ import annotations

import struct
import zlib
from typing import Final

import pytest

from w3xtool.save_container import (
    MAX_SAVE_CONTAINER_BLOCKS,
    looks_like_save_container,
    parse_save_container_header,
    unpack_save_container,
)

SIGNATURE: Final = b"Warcraft III recorded game\x1a\x00"
BLOCK_HEADER_BYTES: Final = 12


def _compress_block(chunk: bytes) -> bytes:
    compressor = zlib.compressobj(level=1, wbits=15)
    return compressor.compress(chunk) + compressor.flush(zlib.Z_SYNC_FLUSH)


def _fold16(value: int) -> int:
    return ((value >> 16) ^ (value & 0xFFFF)) & 0xFFFF


def _checksum(compressed: bytes, compressed_size: int, original_size: int) -> int:
    header = struct.pack("<III", compressed_size, original_size, 0)
    header_fold = _fold16(zlib.crc32(header) & 0xFFFFFFFF)
    data_fold = _fold16(zlib.crc32(compressed) & 0xFFFFFFFF)
    return (data_fold << 16) | header_fold


def _build_container(
    raw: bytes,
    *,
    block_size: int = 1024 * 1024,
    header_version: int = 0,
    declared_original_delta: int = 0,
    extra_subheader: bytes = b"",
) -> bytes:
    header_size = 48 + len(extra_subheader)
    parts = [SIGNATURE]
    blocks: list[tuple[bytes, int, int]] = []
    for start in range(0, len(raw), block_size):
        chunk = raw[start : start + block_size]
        compressed = _compress_block(chunk)
        original_size = len(chunk) + declared_original_delta
        checksum = _checksum(compressed, len(compressed), original_size)
        blocks.append((compressed, original_size, checksum))
    total_size = header_size + sum(
        BLOCK_HEADER_BYTES + len(comp) for comp, _, _ in blocks
    )
    parts.append(
        struct.pack(
            "<5I", header_size, total_size, header_version, len(raw), len(blocks)
        )
    )
    parts.append(extra_subheader)
    for compressed, original_size, checksum in blocks:
        parts.append(struct.pack("<III", len(compressed), original_size, checksum))
        parts.append(compressed)
    return b"".join(parts)


def test_round_trip_returns_raw_bytes_and_block_reports() -> None:
    # Given: a multi-block container built to the documented format.
    raw = bytes(range(256)) * (1024 * 1024 // 256) + b"tail-marker"
    container = _build_container(
        raw, header_version=1, extra_subheader=b"\x01\x02\x03\x04"
    )

    # When: it is unpacked read-only.
    payload = unpack_save_container(container)

    # Then: raw bytes, header metadata, and verified block reports come back.
    assert payload.raw == raw
    assert payload.header.header_version == 1
    assert payload.header.decompressed_size == len(raw)
    assert payload.header.block_count == len(payload.blocks) == 2
    assert payload.header.subheader == b"\x01\x02\x03\x04"
    assert all(block.checksum_ok for block in payload.blocks)
    first, second = payload.blocks
    assert first.original_size == 1024 * 1024
    assert (
        second.offset
        == payload.header.header_size + BLOCK_HEADER_BYTES + first.compressed_size
    )


def test_signature_probe_matches_only_recorded_save_prefix() -> None:
    assert looks_like_save_container(SIGNATURE + b"\x00" * 32)
    assert not looks_like_save_container(b"MPQ\x1a" + b"\x00" * 64)
    assert not looks_like_save_container(b"\x00" * 64)


def test_bad_signature_or_size_is_rejected() -> None:
    with pytest.raises(ValueError, match="signature"):
        parse_save_container_header(b"MPQ\x1a" + b"\x00" * 64)
    with pytest.raises(ValueError, match="too small"):
        parse_save_container_header(SIGNATURE[:20])


@pytest.mark.parametrize("header_size", (0, 32, 10_000))
def test_out_of_range_header_size_is_rejected(header_size: int) -> None:
    container = _build_container(b"payload", extra_subheader=b"\x00" * 8)
    corrupted = bytearray(container)
    struct.pack_into("<I", corrupted, len(SIGNATURE), header_size)

    with pytest.raises(ValueError, match="header_size"):
        unpack_save_container(bytes(corrupted))


def test_block_count_over_limit_is_rejected() -> None:
    container = bytearray(_build_container(b"payload"))
    struct.pack_into(
        "<I", container, len(SIGNATURE) + 16, MAX_SAVE_CONTAINER_BLOCKS + 1
    )

    with pytest.raises(ValueError, match="block count"):
        unpack_save_container(bytes(container))


def test_block_checksum_mismatch_is_rejected() -> None:
    container = bytearray(_build_container(b"hero save payload"))
    container[-1] ^= 0xFF

    with pytest.raises(ValueError, match="checksum mismatch"):
        unpack_save_container(bytes(container))


def test_short_decompress_against_declared_size_is_rejected() -> None:
    # Given: a block whose declared original size exceeds its real stream.
    container = _build_container(b"payload", declared_original_delta=8)

    # When: the container is unpacked strictly.
    with pytest.raises(ValueError, match="declared"):
        unpack_save_container(container)


def test_declared_expansion_over_budget_is_rejected_before_decompression() -> None:
    container = _build_container(b"payload")

    with pytest.raises(ValueError, match="raw budget"):
        unpack_save_container(container, max_raw_bytes=4)


def test_trailing_bytes_after_blocks_are_rejected() -> None:
    container = _build_container(b"payload") + b"\x00\x00"

    with pytest.raises(ValueError, match="trailing"):
        unpack_save_container(container)


def test_missing_block_header_is_rejected() -> None:
    container = _build_container(b"payload")
    truncated = container[:-1]

    with pytest.raises(ValueError):
        unpack_save_container(truncated)
