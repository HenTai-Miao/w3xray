"""Bounded conversion of MPQ block evidence into one immutable ledger."""

from __future__ import annotations

from collections.abc import Sequence

from .archive_inventory_contracts import (
    AnonymousProvenance as AnonymousProvenance,
    FileProvenance as FileProvenance,
    InventoryArchive as InventoryArchive,
    InventoryMetadata as InventoryMetadata,
)
from .archive_inventory_entries import anonymous_entry, named_entry, pure_file_entries
from .extraction_ledger import (
    BlockSource,
    BlockState,
    ExtractionEntry,
    ExtractionLedger,
    build_extraction_ledger,
)


def build_archive_inventory(
    archive: InventoryArchive,
    source_sha256: str,
) -> ExtractionLedger:
    """Read each live block once and record decoded or raw static evidence."""
    blocks = tuple(archive.iter_blocks())
    valid_indexes = {index for index, _block in blocks}
    names_by_block, pure_names = _classify_names(archive, valid_indexes)
    entries: list[ExtractionEntry] = []
    for block_index, block in blocks:
        name = names_by_block.get(block_index)
        if name is not None:
            entries.append(named_entry(archive, block_index, block, name))
        else:
            entries.append(anonymous_entry(archive, block_index, block))
    entries.extend(pure_file_entries(archive, pure_names))
    warnings: Sequence[str] = ()
    container_readable = True
    if isinstance(archive, InventoryMetadata):
        warnings = archive.warnings
        container_readable = archive.container_readable
    if not container_readable:
        entries.append(
            ExtractionEntry(
                block_index=None,
                internal_path="container",
                state=BlockState.DAMAGED,
                source=BlockSource.RAW_PAYLOAD,
                declared_size=len(archive._data),
                written_size=0,
                sha256="",
                encrypted=False,
                error_code="container_unreadable",
                detail="MPQ tables could not be inventoried",
            ),
        )
    return build_extraction_ledger(
        archive.path,
        source_sha256,
        entries,
        warnings=warnings,
    )


def _classify_names(
    archive: InventoryArchive,
    valid_indexes: set[int],
) -> tuple[dict[int, str], tuple[str, ...]]:
    names_by_block: dict[int, str] = {}
    pure_names: list[str] = []
    names = sorted(set(archive.list_files()), key=lambda name: (name.casefold(), name))
    for name in names:
        block_index = archive.block_index_of(name)
        if block_index is None:
            pure_names.append(name)
        elif block_index in valid_indexes:
            names_by_block.setdefault(block_index, name)
    return names_by_block, tuple(pure_names)
