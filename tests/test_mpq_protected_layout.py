"""StormLib-compatible recovery for protected HM3W MPQ layouts."""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Final

import pytest

from w3xtool.archive_diagnostics import (
    ArchiveDiagnosisKind,
    diagnose_archive_open,
)
from w3xtool.mpq import MPQArchive

from .test_mpq_names_locale import build_archive_bytes


_HM3W_HEADER_OFFSET: Final = 512
_A801_HEADER_SIZE: Final = 0xCA30467C
_PACK_HEADER_SIZE: Final = int.from_bytes(b"PACK", "little")


def _with_hm3w_header_size(archive: bytes, header_size: int) -> bytes:
    wrapped = bytearray(_HM3W_HEADER_OFFSET + len(archive))
    wrapped[:4] = b"HM3W"
    wrapped[_HM3W_HEADER_OFFSET:] = archive
    struct.pack_into("<I", wrapped, _HM3W_HEADER_OFFSET + 4, header_size)
    return bytes(wrapped)


def _with_tables_before_header(archive: bytes) -> bytes:
    fields = struct.unpack_from("<4sIIHHIIII", archive)
    hash_position, block_position = fields[5], fields[6]
    hash_size, block_size = fields[7] * 16, fields[8] * 16
    block_end = block_position + block_size
    protected_block_position = _HM3W_HEADER_OFFSET - block_size
    protected_hash_position = protected_block_position - hash_size

    wrapped = bytearray(_HM3W_HEADER_OFFSET + len(archive))
    wrapped[:4] = b"HM3W"
    wrapped[protected_hash_position:protected_block_position] = archive[
        hash_position : hash_position + hash_size
    ]
    wrapped[protected_block_position:_HM3W_HEADER_OFFSET] = archive[
        block_position:block_end
    ]
    wrapped[_HM3W_HEADER_OFFSET : _HM3W_HEADER_OFFSET + 32] = archive[:32]
    struct.pack_into("<I", wrapped, _HM3W_HEADER_OFFSET + 4, _PACK_HEADER_SIZE)
    struct.pack_into(
        "<I",
        wrapped,
        _HM3W_HEADER_OFFSET + 16,
        (protected_hash_position - _HM3W_HEADER_OFFSET) & 0xFFFFFFFF,
    )
    struct.pack_into(
        "<I",
        wrapped,
        _HM3W_HEADER_OFFSET + 20,
        (protected_block_position - _HM3W_HEADER_OFFSET) & 0xFFFFFFFF,
    )
    wrapped[_HM3W_HEADER_OFFSET + block_end :] = archive[block_end:]
    return bytes(wrapped)


def _with_only_hash_table_before_header(archive: bytes) -> bytes:
    fields = struct.unpack_from("<4sIIHHIIII", archive)
    hash_position, hash_count = fields[5], fields[7]
    hash_size = hash_count * 16
    protected_hash_position = _HM3W_HEADER_OFFSET - hash_size
    wrapped = bytearray(_HM3W_HEADER_OFFSET + len(archive))
    wrapped[:4] = b"HM3W"
    wrapped[_HM3W_HEADER_OFFSET:] = archive
    wrapped[protected_hash_position:_HM3W_HEADER_OFFSET] = archive[
        hash_position : hash_position + hash_size
    ]
    struct.pack_into("<I", wrapped, _HM3W_HEADER_OFFSET + 4, _PACK_HEADER_SIZE)
    struct.pack_into(
        "<I",
        wrapped,
        _HM3W_HEADER_OFFSET + 16,
        (protected_hash_position - _HM3W_HEADER_OFFSET) & 0xFFFFFFFF,
    )
    return bytes(wrapped)


def test_non_hm3w_archive_does_not_normalize_large_header(tmp_path: Path) -> None:
    # Given: an ordinary classic MPQ with a protector-sized main header field.
    source = bytearray(build_archive_bytes(b"war3map.j", ((0, b"script"),)))
    struct.pack_into("<I", source, 4, _A801_HEADER_SIZE)
    path = tmp_path / "not-hm3w.w3x"
    path.write_bytes(source)

    # When: the public reader opens a non-HM3W archive.
    # Then: the large header remains invalid instead of being normalized.
    with pytest.raises(ValueError, match="头大小非法"):
        MPQArchive(str(path))


def test_hm3w_nonclassic_version_does_not_normalize_large_header(
    tmp_path: Path,
) -> None:
    # Given: an HM3W-wrapped nonclassic MPQ with a protector-sized header field.
    source = bytearray(
        _with_hm3w_header_size(
            build_archive_bytes(b"war3map.j", ((0, b"script"),)),
            _A801_HEADER_SIZE,
        )
    )
    struct.pack_into("<H", source, _HM3W_HEADER_OFFSET + 12, 1)
    path = tmp_path / "nonclassic.w3x"
    path.write_bytes(source)

    # When: the public reader opens the nonclassic layout.
    # Then: the large header remains invalid instead of being normalized.
    with pytest.raises(ValueError, match="头大小非法"):
        MPQArchive(str(path))


def test_hm3w_header_smaller_than_32_bytes_is_rejected(tmp_path: Path) -> None:
    # Given: a protected classic MPQ whose stored header is structurally short.
    source = _with_hm3w_header_size(
        build_archive_bytes(b"war3map.j", ((0, b"script"),)),
        31,
    )
    path = tmp_path / "short-header.w3x"
    path.write_bytes(source)

    # When: the public reader opens the truncated logical header.
    # Then: protected normalization cannot weaken the 32-byte lower bound.
    with pytest.raises(ValueError, match="头大小非法"):
        MPQArchive(str(path))


def test_hm3w_rejects_only_one_wrapped_table_offset(tmp_path: Path) -> None:
    # Given: a protected classic MPQ where only the hash table wraps pre-header.
    source = build_archive_bytes(b"war3map.j", ((0, b"script"),))
    path = tmp_path / "one-wrapped-table.w3x"
    path.write_bytes(_with_only_hash_table_before_header(source))

    # When: the public reader opens the mixed before/after-table layout.
    # Then: paired wrapping is required before either table can be trusted.
    with pytest.raises(ValueError, match="必须同时回绕"):
        MPQArchive(str(path))


def test_hm3w_classic_archive_normalizes_large_header_size(
    tmp_path: Path,
) -> None:
    # Given: a valid classic MPQ whose HM3W protector replaced the header size.
    payload = b"function main takes nothing returns nothing\nendfunction"
    source = build_archive_bytes(b"war3map.j", ((0, payload),))
    path = tmp_path / "protected-header-size.w3x"
    path.write_bytes(_with_hm3w_header_size(source, _A801_HEADER_SIZE))

    # When: the public archive reader opens the protected layout.
    with MPQArchive(str(path)) as archive:
        script = archive.read_file("war3map.j")
        normalized_header_size = archive.header_size

    # Then: the bounded classic header and its real member remain readable.
    assert normalized_header_size == 32
    assert script == payload


def test_hm3w_classic_archive_resolves_wrapped_table_offsets(
    tmp_path: Path,
) -> None:
    # Given: a protector placed both classic tables before the aligned MPQ header.
    payload = b"function main takes nothing returns nothing\nendfunction"
    source = build_archive_bytes(b"war3map.j", ((0, payload),))
    path = tmp_path / "protected-table-offsets.w3x"
    path.write_bytes(_with_tables_before_header(source))

    # When: the public archive reader opens the wrapped-offset layout.
    with MPQArchive(str(path)) as archive:
        script = archive.read_file("war3map.j")

    # Then: the pre-header tables resolve without weakening block bounds.
    assert script == payload


def test_hm3w_wrapped_offsets_are_diagnosed_as_valid_structure(
    tmp_path: Path,
) -> None:
    # Given: the same pre-header table layout fails later for an unrelated reason.
    source = build_archive_bytes(b"war3map.j", ((0, b"script"),))
    path = tmp_path / "diagnosed-protected-layout.w3x"
    path.write_bytes(_with_tables_before_header(source))

    # When: bounded open-failure diagnostics inspect the original file.
    diagnosis = diagnose_archive_open(str(path), ValueError("later decode failure"))

    # Then: the compatible header is not mislabeled as table damage.
    assert diagnosis.kind is ArchiveDiagnosisKind.READ_ERROR
    assert "structure=valid" in diagnosis.evidence


def test_protected_diagnosis_reports_normalized_header_and_wrap(
    tmp_path: Path,
) -> None:
    # Given: a coherent protected classic candidate with both tables pre-header.
    source = build_archive_bytes(b"war3map.j", ((0, b"script"),))
    path = tmp_path / "diagnosis-evidence.w3x"
    path.write_bytes(_with_tables_before_header(source))

    # When: bounded diagnostics inspect the candidate after a later failure.
    diagnosis = diagnose_archive_open(str(path), ValueError("later failure"))

    # Then: evidence exposes the same normalized layout policy as the reader.
    assert diagnosis.kind is ArchiveDiagnosisKind.READ_ERROR
    assert "effective_header_size=32" in diagnosis.evidence
    assert "protected_classic=true" in diagnosis.evidence
    assert "table_offsets_wrapped=true" in diagnosis.evidence
    assert {
        "format_version=0",
        "hash_table_start=368",
        "hash_table_end=496",
        "block_table_start=496",
        "block_table_end=512",
    } <= set(diagnosis.evidence)


def test_non_hm3w_large_header_is_diagnosed_as_damage(tmp_path: Path) -> None:
    # Given: an ordinary archive with a protector-sized stored header field.
    source = bytearray(build_archive_bytes(b"war3map.j", ((0, b"script"),)))
    struct.pack_into("<I", source, 4, _A801_HEADER_SIZE)
    path = tmp_path / "diagnostic-not-hm3w.w3x"
    path.write_bytes(source)

    # When: bounded diagnostics validate the ordinary classic candidate.
    diagnosis = diagnose_archive_open(str(path))

    # Then: only HM3W candidates may normalize the oversized header.
    assert diagnosis.kind is ArchiveDiagnosisKind.TABLE_DAMAGE
    assert any("头大小非法" in item for item in diagnosis.evidence)


def test_diagnosis_rejects_only_one_wrapped_table_offset(tmp_path: Path) -> None:
    # Given: a protected classic candidate where only the hash table wraps.
    source = build_archive_bytes(b"war3map.j", ((0, b"script"),))
    path = tmp_path / "diagnostic-one-wrap.w3x"
    path.write_bytes(_with_only_hash_table_before_header(source))

    # When: bounded diagnostics validate its table-offset relationship.
    diagnosis = diagnose_archive_open(str(path))

    # Then: mixed wrapping is diagnosed as structural damage.
    assert diagnosis.kind is ArchiveDiagnosisKind.TABLE_DAMAGE
    assert any("必须同时回绕" in item for item in diagnosis.evidence)
