from __future__ import annotations

import hashlib
import struct
import zlib
from pathlib import Path

import pytest

import w3xtool.mpq as mpq_facade
from w3xtool.explode import explode
from w3xtool.mpq import (
    FLAG_COMPRESS,
    FLAG_ENCRYPTED,
    FLAG_EXISTS,
    MPQArchive,
    _Block,
    _decompress_sector,
    guess_extension,
)
from w3xtool.mpq_block_reader import parse_sector_offsets, read_mpq_block
from w3xtool.mpq_compression import MPQCompressionError, decompress_mpq_sector


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "reference"
CHAIN_FIXTURES = {
    "stormlib-compression-huffman-adpcm-mono.bin": (
        0x41,
        "f0350d3b198d3ffc9670ce0a327958ba4ac3b93a8a326311ae872308725067aa",
    ),
    "stormlib-compression-huffman-adpcm-stereo.bin": (
        0x81,
        "d9ee9241b07e3a083d1f3d7b8050494f464e9cfd8b3cf91c0488d2c3cda861c1",
    ),
    "stormlib-compression-zlib-sparse.bin": (
        0x22,
        "f4bac05b014054278e686c26af2e7a94654cc718693d9c6ae89da9e4948f81b3",
    ),
}


def _read_fixture(
    name: str, requested_mask: int, expected_sha256: str
) -> tuple[bytes, bytes]:
    path = FIXTURE_DIR / name
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == expected_sha256
    assert len(raw) >= 16
    magic, stored_mask, compressed_len, expected_len = struct.unpack_from("<4sIII", raw)
    assert magic == b"W3CF"
    assert stored_mask == requested_mask
    assert len(raw) == 16 + compressed_len + expected_len
    compressed = raw[16 : 16 + compressed_len]
    expected = raw[16 + compressed_len :]
    assert compressed[0] == requested_mask
    return compressed, expected


def _sparse_encode(data: bytes) -> bytes:
    zero_count = len(data) - len(data.lstrip(b"\x00"))
    literal = data[zero_count:]
    assert 3 <= zero_count <= 130 and 1 <= len(literal) <= 128
    controls = bytes((zero_count - 3, 0x80 | (len(literal) - 1)))
    return len(data).to_bytes(4, "big") + controls[:1] + controls[1:] + literal


@pytest.mark.parametrize(
    "fixture_name,fixture", CHAIN_FIXTURES.items()
)
def test_stormlib_combined_compression_fixture(
    fixture_name: str, fixture: tuple[int, str]
) -> None:
    requested_mask, expected_sha256 = fixture
    compressed, expected = _read_fixture(
        fixture_name, requested_mask, expected_sha256
    )

    actual = decompress_mpq_sector(compressed, len(expected))

    assert actual == expected


def test_reverse_chain_decodes_zlib_before_sparse() -> None:
    expected = b"\x00" * 32 + b"StormLib chain parity"
    compressed = bytes((0x22,)) + zlib.compress(_sparse_encode(expected))

    actual = decompress_mpq_sector(compressed, len(expected))

    assert actual == expected


def test_dual_adpcm_bits_are_rejected() -> None:
    with pytest.raises(MPQCompressionError, match="ADPCM"):
        decompress_mpq_sector(b"\xC0payload", 64)


def test_unknown_compression_bits_are_rejected() -> None:
    with pytest.raises(MPQCompressionError, match="unsupported bits 0x04"):
        decompress_mpq_sector(b"\x04payload", 64)


def test_corrupt_chained_stream_is_rejected() -> None:
    with pytest.raises(MPQCompressionError, match="zlib"):
        decompress_mpq_sector(b"\x22not-zlib", 64)


def test_zlib_output_is_bounded_and_trailing_data_is_rejected() -> None:
    compressed = bytes((0x02,)) + zlib.compress(b"too long")
    assert decompress_mpq_sector(compressed, 3) == b"too"

    with pytest.raises(MPQCompressionError, match="trailing"):
        decompress_mpq_sector(compressed + b"stale", 32)


def test_empty_sector_and_valid_short_final_sector_are_preserved() -> None:
    assert decompress_mpq_sector(b"", 0) == b""
    assert decompress_mpq_sector(b"\x00short", 32) == b"short"


def test_public_reexport_uses_new_dispatcher() -> None:
    assert _decompress_sector is decompress_mpq_sector


def test_mpq_facade_preserves_file_type_guessing() -> None:
    assert guess_extension(b"BLP2payload") == "blp"
    assert guess_extension(b"\x89PNG\r\n\x1a\npayload") == "png"


@pytest.mark.parametrize(
    "text",
    (
        b"Version { FormatVersion 800, }",
        b"function main takes nothing returns nothing",
    ),
)
def test_mpq_facade_preserves_ascii_model_and_script_guessing(text: bytes) -> None:
    assert guess_extension(text) == "mdl"


def test_block_reader_interfaces_are_available() -> None:
    raw = struct.pack("<3I", 12, 16, 20) + b"abcdefgh"

    assert parse_sector_offsets(raw, 3, None) == [12, 16, 20]
    assert callable(read_mpq_block)


def test_mpq_facade_preserves_explode_compatibility_name() -> None:
    assert mpq_facade.explode is explode


def test_named_out_of_range_block_preserves_string_key_error() -> None:
    archive = object.__new__(MPQArchive)
    archive._data = b""
    archive.archive_offset = 0
    archive.sector_size = 4096
    block = _Block(file_pos=1, comp_size=1, file_size=1, flags=FLAG_EXISTS)

    with pytest.raises(KeyError) as captured:
        archive._read_block(block, "named.txt")

    assert captured.value.args == ("named.txt",)


@pytest.mark.parametrize(
    ("file_pos", "comp_size"),
    ((17, 8), (12, 8)),
    ids=("out-of-range-file-pos", "truncated-comp-size"),
)
def test_recover_block_key_returns_none_for_malformed_block(
    file_pos: int, comp_size: int
) -> None:
    archive = object.__new__(MPQArchive)
    archive._data = b"\x00" * 16
    archive.archive_offset = 0
    archive.sector_size = 4096
    block = _Block(
        file_pos=file_pos,
        comp_size=comp_size,
        file_size=4096,
        flags=FLAG_EXISTS | FLAG_ENCRYPTED | FLAG_COMPRESS,
    )

    recovered_key = archive.recover_block_key(block)

    assert recovered_key is None


def test_single_sector_offset_must_fit_inside_block() -> None:
    with pytest.raises(ValueError, match="越界"):
        parse_sector_offsets(struct.pack("<I", 9999), 1, None)
