"""Bounded MPQ/UserData header discovery and classic table parsing."""

from __future__ import annotations

import mmap
import struct
from dataclasses import dataclass
from typing import Final

from .mpq_constants import (
    HASH_FILE_KEY,
    MPQ_ALIGNMENT,
    MPQ_HEADER_MAGIC,
    MPQ_HEADER_SIZE_V1,
    MPQ_USER_DATA_MAGIC,
    UINT32_MAX,
    WAR3_MAP_MAGIC,
)
from .mpq_crypto import _decrypt, hash_name_bytes
from .mpq_names import HashEntry


@dataclass(frozen=True, slots=True)
class MPQLayout:
    archive_offset: int
    header_size: int
    format_version: int
    sector_shift: int
    hash_table_offset: int
    block_table_offset: int
    hash_count: int
    block_count: int


@dataclass(frozen=True, slots=True)
class _Block:
    file_pos: int
    comp_size: int
    file_size: int
    flags: int


@dataclass(frozen=True, slots=True)
class MPQLayoutError(ValueError):
    detail: str

    def __str__(self) -> str:
        return self.detail


type ArchiveBytes = bytes | mmap.mmap

_HEADER_SCAN_LIMIT: Final = 16 * 1024 * 1024
_MAX_TABLE_ENTRIES: Final = 1 << 18


def normalize_classic_header_size(
    archive_offset: int,
    stored_header_size: int,
    file_size: int,
    *,
    protected_classic: bool,
) -> int:
    """Return the bounded effective header size for one classic candidate."""
    if stored_header_size < MPQ_HEADER_SIZE_V1 or (
        not protected_classic and archive_offset + stored_header_size > file_size
    ):
        raise MPQLayoutError(f"MPQ 头大小非法：{stored_header_size}")
    return MPQ_HEADER_SIZE_V1 if protected_classic else stored_header_size


def classic_table_offsets_use_wrap(
    archive_offset: int,
    hash_position: int,
    block_position: int,
    *,
    protected_classic: bool,
) -> bool:
    """Validate that a protected layout wraps both tables or neither table."""
    if not protected_classic:
        return False
    hash_wraps = archive_offset + hash_position > UINT32_MAX
    block_wraps = archive_offset + block_position > UINT32_MAX
    if hash_wraps != block_wraps:
        raise MPQLayoutError("MPQ hash/block 表偏移必须同时回绕")
    return hash_wraps


def resolve_classic_table_offset(
    archive_offset: int,
    stored_offset: int,
    *,
    wrap_32bit: bool,
) -> int:
    """Resolve a classic MPQ table position using its container arithmetic."""
    absolute = archive_offset + stored_offset
    return absolute & 0xFFFFFFFF if wrap_32bit else absolute


def validate_classic_table_budget(
    hash_count: int,
    block_count: int,
    block_offset: int,
    file_size: int,
) -> None:
    """Reject table layouts whose readable entries exceed fixed memory budgets."""
    if hash_count > _MAX_TABLE_ENTRIES:
        raise MPQLayoutError(f"MPQ hash 表过大：{hash_count}")
    readable_blocks = min(block_count, (file_size - block_offset) // 16)
    if readable_blocks > _MAX_TABLE_ENTRIES:
        raise MPQLayoutError(f"MPQ block 表过大：{readable_blocks}")


def locate_mpq_layout(data: ArchiveBytes) -> MPQLayout:
    """Locate the first valid main header, honoring an authoritative UserData wrapper."""
    if data[:4] == MPQ_USER_DATA_MAGIC:
        return _layout_from_user_data(data, 0)

    last_error: MPQLayoutError | None = None
    offset = 0
    scan_end = min(len(data), _HEADER_SCAN_LIMIT)
    while offset + MPQ_HEADER_SIZE_V1 <= scan_end:
        magic = data[offset : offset + 4]
        if magic in (MPQ_HEADER_MAGIC, MPQ_USER_DATA_MAGIC):
            try:
                if magic == MPQ_USER_DATA_MAGIC:
                    return _layout_from_user_data(data, offset)
                return _parse_main_header(data, offset)
            except (ValueError, struct.error) as error:
                last_error = MPQLayoutError(str(error))
        offset += MPQ_ALIGNMENT
    if last_error is not None:
        raise last_error
    raise MPQLayoutError("没找到 MPQ 头（不是有效的 .w3x/.w3n？）")


def _layout_from_user_data(data: ArchiveBytes, offset: int) -> MPQLayout:
    if offset + 16 > len(data):
        raise MPQLayoutError("MPQ UserData 头被截断")
    _magic, user_size, header_offset, user_header_size = struct.unpack_from(
        "<4sIII", data, offset
    )
    if user_header_size > user_size or user_size > header_offset:
        raise MPQLayoutError("MPQ UserData 大小或头偏移非法")
    archive_offset = offset + header_offset
    if archive_offset + MPQ_HEADER_SIZE_V1 > len(data):
        raise MPQLayoutError("MPQ UserData 指向文件范围外")
    if data[archive_offset : archive_offset + 4] != MPQ_HEADER_MAGIC:
        raise MPQLayoutError("MPQ UserData 未指向有效 MPQ 头")
    return _parse_main_header(data, archive_offset)


def _parse_main_header(data: ArchiveBytes, offset: int) -> MPQLayout:
    fields = struct.unpack_from("<4sIIHHIIII", data, offset)
    (
        magic,
        header_size,
        _archive_size,
        version,
        shift,
        hash_pos,
        block_pos,
        hashes,
        blocks,
    ) = fields
    if magic != MPQ_HEADER_MAGIC:
        raise MPQLayoutError("无效的 MPQ 主头签名")
    protected_classic = data[:4] == WAR3_MAP_MAGIC and version == 0
    header_size = normalize_classic_header_size(
        offset,
        header_size,
        len(data),
        protected_classic=protected_classic,
    )
    if shift > 20:
        raise MPQLayoutError(f"MPQ 扇区大小非法：shift={shift}")
    if hashes <= 0 or hashes & (hashes - 1):
        raise MPQLayoutError(f"MPQ hash 表大小非法（应为 2 的幂）：{hashes}")
    classic_table_offsets_use_wrap(
        offset,
        hash_pos,
        block_pos,
        protected_classic=protected_classic,
    )
    hash_offset = resolve_classic_table_offset(
        offset,
        hash_pos,
        wrap_32bit=protected_classic,
    )
    block_offset = resolve_classic_table_offset(
        offset,
        block_pos,
        wrap_32bit=protected_classic,
    )
    if hash_offset < 0 or hash_offset + hashes * 16 > len(data):
        raise MPQLayoutError("MPQ hash 表越界（文件损坏或非标准）")
    if block_offset < 0 or block_offset > len(data):
        raise MPQLayoutError("MPQ block 表起点越界（文件损坏或非标准）")
    validate_classic_table_budget(hashes, blocks, block_offset, len(data))
    return MPQLayout(
        archive_offset=offset,
        header_size=header_size,
        format_version=version,
        sector_shift=shift,
        hash_table_offset=hash_offset,
        block_table_offset=block_offset,
        hash_count=hashes,
        block_count=blocks,
    )


def read_mpq_tables(
    data: ArchiveBytes, layout: MPQLayout
) -> tuple[list[HashEntry], list[_Block]]:
    """Decrypt bounded classic hash and block tables for a validated layout."""
    hash_raw = data[
        layout.hash_table_offset : layout.hash_table_offset + layout.hash_count * 16
    ]
    hash_raw = _decrypt(
        bytes(hash_raw), hash_name_bytes(b"(hash table)", HASH_FILE_KEY)
    )
    hashes: list[HashEntry] = []
    for index in range(layout.hash_count):
        name_a, name_b, locale, platform, _reserved, block_index = struct.unpack_from(
            "<IIHBBI", hash_raw, index * 16
        )
        hashes.append(HashEntry(name_a, name_b, locale, platform, block_index))

    block_raw = data[
        layout.block_table_offset : layout.block_table_offset + layout.block_count * 16
    ]
    block_raw = _decrypt(
        bytes(block_raw), hash_name_bytes(b"(block table)", HASH_FILE_KEY)
    )
    blocks = [
        _Block(*struct.unpack_from("<IIII", block_raw, index * 16))
        for index in range(len(block_raw) // 16)
    ]
    return hashes, blocks
