"""MPQ byte-name hashing and StormLib-compatible locale selection."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from w3xtool.mpq import (
    FLAG_ENCRYPTED,
    FLAG_EXISTS,
    FLAG_SINGLE_UNIT,
    HASH_FILE_KEY,
    HASH_NAME_A,
    HASH_NAME_B,
    HASH_TABLE_OFFSET,
    MPQArchive,
)
from w3xtool.mpq_crypto import CRYPT_TABLE, hash_name_bytes
from w3xtool.mpq_names import HashEntry, encoded_name_candidates, select_hash_entry


STORMLIB_GBK_NAME_A = 0x24B9C622


def _encrypt(data: bytes, key: int) -> bytes:
    count = len(data) // 4
    values = struct.unpack(f"<{count}I", data[: count * 4])
    encrypted: list[int] = []
    seed1 = key & 0xFFFFFFFF
    seed2 = 0xEEEEEEEE
    for value in values:
        seed2 = (seed2 + CRYPT_TABLE[0x400 + (seed1 & 0xFF)]) & 0xFFFFFFFF
        encrypted.append((value ^ ((seed1 + seed2) & 0xFFFFFFFF)) & 0xFFFFFFFF)
        seed1 = (
            ((~seed1 & 0xFFFFFFFF) << 0x15) + 0x11111111 | (seed1 >> 0x0B)
        ) & 0xFFFFFFFF
        seed2 = (value + seed2 + (seed2 << 5) + 3) & 0xFFFFFFFF
    return struct.pack(f"<{count}I", *encrypted) + data[count * 4 :]


def build_archive_bytes(
    name_bytes: bytes,
    localized_payloads: tuple[tuple[int, bytes], ...],
    *,
    encrypted: bool = False,
    reserved: int = 0,
) -> bytes:
    """Build a small real MPQ with duplicate locale hashes for one byte name."""
    hash_count = 8
    block_count = len(localized_payloads)
    hash_pos = 32
    block_pos = hash_pos + hash_count * 16
    data_pos = block_pos + block_count * 16
    flags = FLAG_EXISTS | FLAG_SINGLE_UNIT
    if encrypted:
        flags |= FLAG_ENCRYPTED

    blocks: list[bytes] = []
    payloads: list[bytes] = []
    position = data_pos
    basename = name_bytes.replace(b"/", b"\\").rsplit(b"\\", 1)[-1]
    file_key = hash_name_bytes(basename, HASH_FILE_KEY)
    for _locale, payload in localized_payloads:
        stored = _encrypt(payload, file_key) if encrypted else payload
        blocks.append(struct.pack("<IIII", position, len(stored), len(payload), flags))
        payloads.append(stored)
        position += len(stored)

    empty = struct.pack("<IIHHI", 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFF, 0xFFFF, 0xFFFFFFFF)
    hashes = [empty] * hash_count
    start = hash_name_bytes(name_bytes, HASH_TABLE_OFFSET) & (hash_count - 1)
    name_a = hash_name_bytes(name_bytes, HASH_NAME_A)
    name_b = hash_name_bytes(name_bytes, HASH_NAME_B)
    for offset, (locale, _payload) in enumerate(localized_payloads):
        hashes[(start + offset) & (hash_count - 1)] = struct.pack(
            "<IIHBBI", name_a, name_b, locale, 0, reserved, offset
        )

    hash_bytes = b"".join(hashes)
    block_bytes = b"".join(blocks)
    header = struct.pack(
        "<4sIIHHIIII",
        b"MPQ\x1a",
        32,
        position,
        0,
        3,
        hash_pos,
        block_pos,
        hash_count,
        block_count,
    )
    return b"".join(
        (
            header,
            _encrypt(hash_bytes, hash_name_bytes(b"(hash table)", HASH_FILE_KEY)),
            _encrypt(block_bytes, hash_name_bytes(b"(block table)", HASH_FILE_KEY)),
            *payloads,
        )
    )


def test_gbk_filename_hashes_bytes_not_unicode_codepoints() -> None:
    # Given/When: an explicit Warcraft legacy codec encodes a Chinese MPQ name.
    candidates = encoded_name_candidates("单位数据.txt", legacy_codecs=("gbk",))

    # Then: hashing uses those exact bytes and StormLib's ASCII-only case table.
    assert candidates == ("单位数据.txt".encode("gbk"),)
    assert hash_name_bytes(candidates[0], HASH_NAME_A) == STORMLIB_GBK_NAME_A


def test_encoded_candidates_are_unique_and_ascii_collapses() -> None:
    # Given/When: aliases encode an ASCII name to identical byte sequences.
    candidates = encoded_name_candidates(
        "war3map.j", legacy_codecs=("utf-8", "gbk", "gb18030")
    )

    # Then: the deterministic result contains one candidate only.
    assert candidates == (b"war3map.j",)


def test_unsupported_legacy_codec_is_rejected() -> None:
    # Given/When/Then: invalid configuration is not silently ignored.
    with pytest.raises(LookupError):
        encoded_name_candidates("单位数据.txt", legacy_codecs=("not-a-codec",))


def test_locale_selection_prefers_requested_then_last_neutral() -> None:
    # Given: duplicate neutral entries surround duplicate requested-locale entries.
    entries = (
        HashEntry(1, 2, 0, 0, 1),
        HashEntry(1, 2, 0, 0, 3),
        HashEntry(1, 2, 0x0404, 0, 2),
        HashEntry(1, 2, 0x0404, 0, 4),
    )

    # When: three locale requests select from the same duplicate hash rows.
    exact = select_hash_entry(entries, locale_id=0x0404)
    fallback = select_hash_entry(entries, locale_id=0x0804)
    neutral = select_hash_entry(entries, locale_id=0)

    # Then: the first exact pair wins; fallback retains the last neutral.
    assert exact is not None and exact.block_index == 2
    assert fallback is not None and fallback.block_index == 3
    assert neutral is not None and neutral.block_index == 3


def test_locale_selection_requires_exact_nonzero_platform_pair() -> None:
    # Given: partial locale/platform matches precede one exact compound LCID match.
    entries = (
        HashEntry(1, 2, 0x0404, 0, 1),
        HashEntry(1, 2, 0, 2, 2),
        HashEntry(1, 2, 0x0404, 2, 3),
    )

    # When: the compound locale/platform request is selected.
    selected = select_hash_entry(entries, locale_id=0x0404, platform=2)

    # Then: a nonzero request returns only the exact locale/platform pair.
    assert selected is not None and selected.block_index == 3


def test_gbk_lookup_reuses_matching_candidate_for_encrypted_file_key(
    tmp_path: Path,
) -> None:
    # Given: both table hashes and encryption key use a GBK filename candidate.
    name = "目录\\单位数据.txt"
    path = tmp_path / "gbk-name.w3x"
    path.write_bytes(
        build_archive_bytes(name.encode("gbk"), ((0, b"GBK!"),), encrypted=True)
    )

    # When: the archive is configured with the matching legacy codec.
    with MPQArchive(str(path), legacy_codecs=("gbk",)) as archive:
        payload = archive.read_file(name)

    # Then: lookup and basename-key decryption use the same candidate bytes.
    assert payload == b"GBK!"


def test_archive_locale_configuration_does_not_leak_between_instances(
    tmp_path: Path,
) -> None:
    # Given: one archive has a requested locale plus two neutral fallbacks.
    path = tmp_path / "locales.w3x"
    path.write_bytes(
        build_archive_bytes(
            b"war3map.j", ((0, b"ONE!"), (0, b"LAST"), (0x0404, b"EXACT"))
        )
    )

    # When: two independent readers request different locales.
    with MPQArchive(str(path), locale_id=0x0404) as exact:
        exact_payload = exact.read_file("war3map.j")
    with MPQArchive(str(path), locale_id=0x0804) as fallback:
        fallback_payload = fallback.read_file("war3map.j")

    # Then: each reader applies only its own locale preference.
    assert exact_payload == b"EXACT"
    assert fallback_payload == b"LAST"


def test_hash_reserved_byte_does_not_change_platform_selection(tmp_path: Path) -> None:
    # Given: a valid neutral-platform hash entry uses its reserved byte.
    path = tmp_path / "reserved-byte.w3x"
    path.write_bytes(
        build_archive_bytes(
            b"war3mapImported\\BTNItem.blp",
            ((0, b"BLP1"),),
            reserved=0xFF,
        )
    )

    # When: the exact named member is read through normal locale selection.
    with MPQArchive(str(path)) as archive:
        payload = archive.read_file(r"war3mapImported\BTNItem.blp")

    # Then: the reserved byte cannot impersonate a non-neutral platform.
    assert payload == b"BLP1"
