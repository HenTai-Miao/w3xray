"""Named, anonymous, and supplemental extraction-ledger entries."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from .archive_inventory_contracts import (
    AnonymousProvenance,
    FileProvenance,
    InventoryArchive,
)
from .archive_raw_evidence import raw_or_damaged_entry
from .extraction_ledger import BlockSource, BlockState, ExtractionEntry
from .mpq import FLAG_ENCRYPTED, guess_extension
from .mpq_layout import _Block


def named_entry(
    archive: InventoryArchive,
    block_index: int,
    block: _Block,
    name: str,
) -> ExtractionEntry:
    """Read one reliable name or preserve its raw block evidence."""
    try:
        payload = archive.read_file(name)
    except (KeyError, OSError, ValueError) as exc:
        return raw_or_damaged_entry(
            archive,
            block_index,
            block,
            detail=f"named read failed for {name}: {type(exc).__name__}",
        )
    source = file_source(archive, name)
    state = (
        BlockState.SUPPLEMENTED
        if source in {BlockSource.COMPAT_PLAINTEXT, BlockSource.AUTHOR_PLAINTEXT}
        else BlockState.DECODED
    )
    return _verified_entry(block_index, name, block, payload, state, source)


def anonymous_entry(
    archive: InventoryArchive,
    block_index: int,
    block: _Block,
) -> ExtractionEntry:
    """Try automatic recovery and compatibility keys before raw fallback."""
    if isinstance(archive, AnonymousProvenance):
        payload, source = archive.read_block_anon_with_source(block_index, block)
    else:
        payload = archive.read_block_anon(block)
        source = BlockSource.ARCHIVE_RECOVERED
    if payload is None:
        return raw_or_damaged_entry(
            archive,
            block_index,
            block,
            detail="anonymous block could not be decoded",
        )
    path = f"Unknown/block_{block_index:06d}.{guess_extension(payload)}"
    return _verified_entry(
        block_index,
        path,
        block,
        payload,
        BlockState.DECODED,
        source,
    )


def pure_file_entries(
    archive: InventoryArchive,
    names: Sequence[str],
) -> tuple[ExtractionEntry, ...]:
    """Inventory supplemental plaintext that has no base MPQ block."""
    entries: list[ExtractionEntry] = []
    for name in names:
        try:
            payload = archive.read_file(name)
        except (KeyError, OSError, ValueError) as exc:
            entries.append(
                ExtractionEntry(
                    None,
                    name,
                    BlockState.DAMAGED,
                    file_source(archive, name),
                    0,
                    0,
                    "",
                    False,
                    "supplemental_read_failed",
                    type(exc).__name__,
                ),
            )
            continue
        entries.append(
            ExtractionEntry(
                None,
                name,
                BlockState.SUPPLEMENTED,
                file_source(archive, name),
                len(payload),
                len(payload),
                hashlib.sha256(payload).hexdigest(),
                False,
                "",
                "",
            ),
        )
    return tuple(entries)


def file_source(archive: InventoryArchive, name: str) -> BlockSource:
    """Return explicit provenance or the named-archive default."""
    if isinstance(archive, FileProvenance):
        return archive.file_source(name)
    return BlockSource.ARCHIVE_NAMED


def _verified_entry(
    block_index: int,
    path: str,
    block: _Block,
    payload: bytes,
    state: BlockState,
    source: BlockSource,
) -> ExtractionEntry:
    return ExtractionEntry(
        block_index,
        path,
        state,
        source,
        block.file_size,
        len(payload),
        hashlib.sha256(payload).hexdigest(),
        bool(block.flags & FLAG_ENCRYPTED),
        "",
        "",
    )
