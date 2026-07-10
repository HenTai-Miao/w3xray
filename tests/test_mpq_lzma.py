from __future__ import annotations

import hashlib
import lzma
import struct
from pathlib import Path

import pytest

from w3xtool.mpq_compression import MPQCompressionError, decompress_mpq_sector


FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "reference" / "stormlib-compression-lzma.bin"
)
FIXTURE_SHA256 = "085b7d6d8c036bbb8feb83f518ea51927970b7a6803ef2549711f981ba5591d3"
LZMA_FILTER = {"id": lzma.FILTER_LZMA1, "dict_size": 1 << 20, "lc": 3, "lp": 0, "pb": 2}


def _lzma_sector(data: bytes, *, declared_size: int | None = None) -> bytes:
    props = bytes((0x5D,)) + (1 << 20).to_bytes(4, "little")
    stream = lzma.compress(data, format=lzma.FORMAT_RAW, filters=[LZMA_FILTER])
    size = len(data) if declared_size is None else declared_size
    return b"\x12\x00" + props + size.to_bytes(8, "little") + stream


def _read_fixture() -> tuple[bytes, bytes]:
    raw = FIXTURE_PATH.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == FIXTURE_SHA256
    assert len(raw) >= 16
    magic, requested_mask, compressed_len, expected_len = struct.unpack_from("<4sIII", raw)
    assert magic == b"W3CF"
    assert requested_mask == 0x12
    assert len(raw) == 16 + compressed_len + expected_len
    compressed = raw[16 : 16 + compressed_len]
    expected = raw[16 + compressed_len :]
    assert compressed[0] == requested_mask
    return compressed, expected


def test_stormlib_lzma_marker_dispatches_as_lzma() -> None:
    compressed, expected = _read_fixture()

    actual = decompress_mpq_sector(compressed, len(expected))

    assert actual == expected


def test_lzma_marker_is_standalone_not_zlib_and_bzip_flags() -> None:
    expected = b"LZMA marker parity" * 8

    actual = decompress_mpq_sector(_lzma_sector(expected), len(expected))

    assert actual == expected


@pytest.mark.parametrize("payload", (b"\x12", b"\x12\x00", b"\x12" + b"\x00" * 13))
def test_truncated_lzma_header_or_stream_is_rejected(payload: bytes) -> None:
    with pytest.raises(MPQCompressionError, match="LZMA"):
        decompress_mpq_sector(payload, 64)


def test_lzma_filter_and_properties_are_validated() -> None:
    sector = _lzma_sector(b"data")
    with pytest.raises(MPQCompressionError, match="filter"):
        decompress_mpq_sector(sector[:1] + b"\x01" + sector[2:], 4)

    with pytest.raises(MPQCompressionError, match="properties"):
        decompress_mpq_sector(sector[:2] + b"\xFF" + sector[3:], 4)


def test_lzma_dictionary_is_bounded_before_decoder_allocation() -> None:
    sector = _lzma_sector(b"data")
    oversized = sector[:3] + (0xFFFFFFFF).to_bytes(4, "little") + sector[7:]

    with pytest.raises(MPQCompressionError, match="dictionary"):
        decompress_mpq_sector(oversized, 4)


def test_lzma_declared_size_must_fit_contract_and_match_output() -> None:
    with pytest.raises(MPQCompressionError, match="declared"):
        decompress_mpq_sector(_lzma_sector(b"data", declared_size=5), 4)

    with pytest.raises(MPQCompressionError, match="size"):
        decompress_mpq_sector(_lzma_sector(b"data", declared_size=3), 4)

    with pytest.raises(MPQCompressionError, match="size"):
        decompress_mpq_sector(_lzma_sector(b"data", declared_size=5), 5)


def test_lzma_zero_output_corruption_and_trailing_data_are_rejected() -> None:
    sector = _lzma_sector(b"data")
    with pytest.raises(MPQCompressionError, match="declared"):
        decompress_mpq_sector(sector, 0)

    with pytest.raises(MPQCompressionError, match="LZMA"):
        decompress_mpq_sector(sector[:-6], 4)

    with pytest.raises(MPQCompressionError, match="trailing"):
        decompress_mpq_sector(sector + b"stale", 4)


def test_lzma_missing_end_marker_is_rejected_after_full_output() -> None:
    expected = b"full output before end marker" * 8
    sector = _lzma_sector(expected)

    with pytest.raises(MPQCompressionError, match="truncated"):
        decompress_mpq_sector(sector[:-1], len(expected))


def test_lzma_valid_short_final_sector_is_preserved() -> None:
    expected = b"short"

    actual = decompress_mpq_sector(_lzma_sector(expected), 32)

    assert actual == expected
