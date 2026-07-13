"""Pure layout validation for bounded MPQ diagnostic candidates."""

from __future__ import annotations

import struct
from typing import Final

from .mpq_layout import (
    MPQLayoutError,
    classic_table_offsets_use_wrap,
    normalize_classic_header_size,
    resolve_classic_table_offset,
    validate_classic_table_budget,
)

MPQ_HEADER: Final = struct.Struct("<4sIIHHIIII")


def validate_mpq_candidate(
    raw: bytes,
    offset: int,
    file_size: int,
    *,
    war3_map: bool,
) -> tuple[str, ...]:
    """Return stable evidence for one aligned MPQ main-header candidate."""
    base = (f"candidate_offset={offset}", f"file_size={file_size}")
    if len(raw) < MPQ_HEADER.size:
        return base + ("header_truncated",)
    (
        _magic,
        header_size,
        _archive_size,
        format_version,
        sector_shift,
        hash_pos,
        block_pos,
        hash_count,
        block_count,
    ) = MPQ_HEADER.unpack(raw)
    fields = base + (
        f"header_size={header_size}",
        f"format_version={format_version}",
        f"hash_count={hash_count}",
        f"block_count={block_count}",
    )
    protected_classic = war3_map and format_version == 0
    try:
        effective_header_size = normalize_classic_header_size(
            offset,
            header_size,
            file_size,
            protected_classic=protected_classic,
        )
        table_offsets_wrapped = classic_table_offsets_use_wrap(
            offset,
            hash_pos,
            block_pos,
            protected_classic=protected_classic,
        )
    except MPQLayoutError as exc:
        return fields + (f"layout_error={exc}",)
    fields += (
        f"effective_header_size={effective_header_size}",
        f"protected_classic={str(protected_classic).lower()}",
        f"table_offsets_wrapped={str(table_offsets_wrapped).lower()}",
    )
    if sector_shift > 20:
        return fields + (f"sector_shift={sector_shift}", "sector_shift_invalid")
    if hash_count <= 0 or hash_count & (hash_count - 1):
        return fields + ("hash_count_not_power_of_two",)
    hash_start = resolve_classic_table_offset(
        offset,
        hash_pos,
        wrap_32bit=protected_classic,
    )
    hash_end = hash_start + hash_count * 16
    fields += (
        f"hash_table_start={hash_start}",
        f"hash_table_end={hash_end}",
    )
    if hash_end > file_size:
        return fields + ("hash_table_oob",)
    block_start = resolve_classic_table_offset(
        offset,
        block_pos,
        wrap_32bit=protected_classic,
    )
    if block_start > file_size:
        return fields + (f"block_table_start={block_start}", "block_table_start_oob")
    block_end = min(file_size, block_start + block_count * 16)
    fields += (
        f"block_table_start={block_start}",
        f"block_table_end={block_end}",
    )
    try:
        validate_classic_table_budget(
            hash_count,
            block_count,
            block_start,
            file_size,
        )
    except MPQLayoutError as exc:
        return fields + (f"layout_error={exc}",)
    if format_version != 0:
        return fields + ("format_unsupported",)
    return fields + ("structure=valid",)
