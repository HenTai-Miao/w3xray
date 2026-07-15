"""Per-block archive inventory built from named, recovered, keyed, and raw evidence."""

from __future__ import annotations

import hashlib

from w3xtool.archive_inventory import build_archive_inventory
from w3xtool.extraction_ledger import BlockSource, BlockState, ExtractionStatus
from w3xtool.mpq import FLAG_ENCRYPTED, FLAG_EXISTS
from w3xtool.mpq_layout import _Block


class _Archive:
    path = "source.w3x"
    archive_offset = 0
    container_readable = True
    warnings = ("overlay-warning",)

    def __init__(self) -> None:
        self._data = b"namedAUTOkeyRAW!"
        self.blocks = (
            _Block(0, 5, 5, FLAG_EXISTS),
            _Block(5, 4, 4, FLAG_EXISTS),
            _Block(9, 3, 3, FLAG_EXISTS | FLAG_ENCRYPTED),
            _Block(12, 4, 9, FLAG_EXISTS | FLAG_ENCRYPTED),
        )

    def list_files(self) -> list[str]:
        return ["war3map.j"]

    def block_index_of(self, name: str) -> int | None:
        return 0 if name == "war3map.j" else None

    def read_file(self, name: str) -> bytes:
        if name == "war3map.j":
            return b"named"
        raise KeyError(name)

    def iter_blocks(self) -> tuple[tuple[int, _Block], ...]:
        return tuple(enumerate(self.blocks))

    def read_block_anon(self, block: _Block) -> bytes | None:
        return b"AUTO" if block is self.blocks[1] else None

    def read_block_anon_with_source(
        self,
        block_index: int,
        block: _Block,
    ) -> tuple[bytes | None, BlockSource]:
        if block_index == 1:
            return b"AUTO", BlockSource.ARCHIVE_RECOVERED
        if block_index == 2:
            return b"key", BlockSource.COMPAT_KEY
        return None, BlockSource.RAW_PAYLOAD

    def file_source(self, _name: str) -> BlockSource:
        return BlockSource.ARCHIVE_NAMED

    def supplemental_files(self) -> tuple[()]:
        return ()


def test_inventory_records_every_live_block_with_stable_paths_and_hashes() -> None:
    # Given: named, automatically recovered, compatibility-key, and raw-only blocks.
    archive = _Archive()

    # When: the archive is inventoried without mutating its source.
    ledger = build_archive_inventory(archive, "f" * 64)

    # Then: every live block has one ordered evidence row and precise provenance.
    assert [entry.block_index for entry in ledger.entries] == [0, 1, 2, 3]
    assert [entry.source for entry in ledger.entries] == [
        BlockSource.ARCHIVE_NAMED,
        BlockSource.ARCHIVE_RECOVERED,
        BlockSource.COMPAT_KEY,
        BlockSource.RAW_PAYLOAD,
    ]
    assert ledger.entries[1].internal_path == "Unknown/block_000001.txt"
    assert ledger.entries[3].internal_path == "UnknownRaw/block_000003.raw"
    assert ledger.entries[3].sha256 == hashlib.sha256(b"RAW!").hexdigest()
    assert ledger.entries[3].state is BlockState.ENCRYPTED_BLOCKED
    assert ledger.status is ExtractionStatus.ENCRYPTED_BLOCKED
    assert ledger.warnings == ("overlay-warning",)


def test_inventory_marks_truncated_raw_payload_as_damaged() -> None:
    # Given: an unresolved block points beyond the source container.
    archive = _Archive()
    archive.blocks = (*archive.blocks[:3], _Block(99, 4, 9, FLAG_EXISTS))

    # When: the fallback payload boundary is checked.
    ledger = build_archive_inventory(archive, "f" * 64)

    # Then: structural damage takes priority over all other states.
    assert ledger.entries[3].state is BlockState.DAMAGED
    assert ledger.entries[3].error_code == "raw_payload_out_of_bounds"
    assert ledger.status is ExtractionStatus.DAMAGED


def test_unreadable_container_with_plaintext_stays_damaged() -> None:
    # Given: an overlay can expose a plaintext file but no MPQ table is readable.
    class PlaintextOnly:
        path = "protected.w3x"
        archive_offset = 0
        _data = b""
        container_readable = False
        warnings: tuple[str, ...] = ()

        def list_files(self) -> list[str]:
            return ["war3map.j"]

        def block_index_of(self, _name: str) -> int | None:
            return None

        def read_file(self, _name: str) -> bytes:
            return b"script"

        def iter_blocks(self) -> tuple[tuple[int, _Block], ...]:
            return ()

        def read_block_anon(self, _block: _Block) -> bytes | None:
            return None

        def file_source(self, _name: str) -> BlockSource:
            return BlockSource.AUTHOR_PLAINTEXT

        def supplemental_files(self) -> tuple[()]:
            return ()

    # When: bytes are useful but the complete block set cannot be proven.
    ledger = build_archive_inventory(PlaintextOnly(), "f" * 64)

    # Then: the result never claims completeness.
    assert ledger.status is ExtractionStatus.DAMAGED
    assert ledger.first_error is not None
    assert ledger.first_error.error_code == "container_unreadable"
