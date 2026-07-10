"""MPQ UserData wrapper and bounded main-header validation."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from w3xtool.mpq import MPQArchive
from w3xtool.mpq_layout import locate_mpq_layout

from .test_mpq_names_locale import build_archive_bytes


def wrap_with_user_data(archive: bytes, payload: bytes = b"author metadata") -> bytes:
    """Wrap an MPQ in the v9.25 TMPQUserData layout."""
    header_offset = 16 + len(payload)
    user_header = struct.pack(
        "<4sIII", b"MPQ\x1b", len(payload), header_offset, len(payload) // 2
    )
    return user_header + payload + archive


def test_mpq_user_data_header_points_to_real_archive(tmp_path: Path) -> None:
    # Given: a valid UserData wrapper points at a complete MPQ.
    archive_bytes = build_archive_bytes(b"war3map.j", ((0, b"function main"),))
    path = tmp_path / "user-data.w3x"
    path.write_bytes(wrap_with_user_data(archive_bytes))

    # When: the wrapped archive is opened through the public reader.
    with MPQArchive(str(path)) as archive:
        script = archive.read_file("war3map.j")

    # Then: all relative table and block offsets use the pointed-to archive base.
    assert script.startswith(b"function main")


def test_aligned_scan_finds_user_data_wrapper_after_prefix(tmp_path: Path) -> None:
    # Given: a protected-map prefix places a UserData wrapper at the next 512-byte boundary.
    archive_bytes = build_archive_bytes(b"war3map.j", ((0, b"function main"),))
    wrapped = b"\x00" * 512 + wrap_with_user_data(archive_bytes)
    path = tmp_path / "prefixed-user-data.w3x"
    path.write_bytes(wrapped)

    # When: the normal bounded recovery scan opens the archive.
    with MPQArchive(str(path)) as archive:
        script = archive.read_file("war3map.j")

    # Then: the UserData-relative target becomes the archive base.
    assert script.startswith(b"function main")


def test_truncated_user_data_header_is_rejected() -> None:
    # Given/When/Then: a signature without all four fields is malformed.
    with pytest.raises(ValueError, match="UserData"):
        locate_mpq_layout(b"MPQ\x1b" + b"\x00" * 8)


@pytest.mark.parametrize(
    ("user_size", "header_offset", "user_header_size"),
    (
        (33, 32, 16),
        (16, 4096, 8),
        (8, 32, 9),
    ),
)
def test_user_data_bounds_are_rejected(
    user_size: int, header_offset: int, user_header_size: int
) -> None:
    # Given: one UserData size relationship or target bound is invalid.
    data = struct.pack(
        "<4sIII", b"MPQ\x1b", user_size, header_offset, user_header_size
    ) + b"\x00" * 64

    # When/Then: validation rejects it before any unbounded scan or table read.
    with pytest.raises(ValueError, match="UserData"):
        locate_mpq_layout(data)


def test_invalid_user_data_target_cannot_fall_through_to_aligned_decoy() -> None:
    # Given: UserData points at an invalid header while a valid MPQ sits at 512.
    real = build_archive_bytes(b"war3map.j", ((0, b"function main"),))
    data = bytearray(512 + len(real))
    data[:16] = struct.pack("<4sIII", b"MPQ\x1b", 16, 128, 8)
    data[128:132] = b"NOPE"
    data[512:] = real

    # When/Then: the wrapper target is authoritative and bounded validation fails.
    with pytest.raises(ValueError, match="MPQ"):
        locate_mpq_layout(bytes(data))


def test_user_data_target_with_invalid_table_bounds_is_rejected() -> None:
    # Given: a pointed-to main header declares a hash table past EOF.
    archive = bytearray(build_archive_bytes(b"war3map.j", ((0, b"function main"),)))
    struct.pack_into("<I", archive, 16, 0xFFFFFF00)
    wrapped = wrap_with_user_data(bytes(archive))

    # When/Then: a valid signature cannot bypass main-table bounds checks.
    with pytest.raises(ValueError, match="hash"):
        locate_mpq_layout(wrapped)
