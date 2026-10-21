"""Raw-payload fallback evidence for undecodable MPQ blocks."""

from __future__ import annotations

import hashlib

from .archive_inventory_contracts import InventoryArchive
from .extraction_ledger import BlockSource, BlockState, ExtractionEntry
from .mpq import FLAG_ENCRYPTED
from .mpq_layout import _Block


def raw_or_damaged_entry(
    archive: InventoryArchive,
    block_index: int,
    block: _Block,
    *,
    detail: str,
) -> ExtractionEntry:
    """Preserve bounded raw bytes or report structural bounds damage."""
    raw = _raw_payload(archive, block)
    if raw is None:
        return ExtractionEntry(
            block_index,
            f"UnknownRaw/block_{block_index:06d}.raw",
            BlockState.DAMAGED,
            BlockSource.RAW_PAYLOAD,
            block.file_size,
            0,
            "",
            bool(block.flags & FLAG_ENCRYPTED),
            "raw_payload_out_of_bounds",
            detail,
        )
    encrypted = bool(block.flags & FLAG_ENCRYPTED)
    return ExtractionEntry(
        block_index,
        f"UnknownRaw/block_{block_index:06d}.raw",
        BlockState.ENCRYPTED_BLOCKED if encrypted else BlockState.RAW_ONLY,
        BlockSource.RAW_PAYLOAD,
        block.file_size,
        len(raw),
        hashlib.sha256(raw).hexdigest(),
        encrypted,
        "missing_static_key" if encrypted else "decode_failed",
        detail,
    )


def _raw_payload(archive: InventoryArchive, block: _Block) -> bytes | None:
    start = archive.archive_offset + block.file_pos
    end = start + block.comp_size
    if start < 0 or end < start or end > len(archive._data):
        return None
    return bytes(archive._data[start:end])
