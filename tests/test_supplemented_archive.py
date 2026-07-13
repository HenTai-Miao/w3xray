"""Archive overlay priority, provenance, and key verification."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from w3xtool.bounded_file import sha256_regular_file
from w3xtool.extraction_ledger import BlockSource
from w3xtool.mpq import FLAG_ENCRYPTED, FLAG_EXISTS, _Block
from w3xtool.supplemental_evidence import (
    SupplementalEvidence,
    SupplementalEvidenceError,
    SupplementalFile,
    SupplementalKey,
)
from w3xtool.supplemented_archive import SupplementedArchive


class _BaseArchive:
    path = "source.w3x"
    archive_offset = 0
    sector_size = 4096

    def __init__(self) -> None:
        self._data = b"namedautomaticraw"
        self.block_table = [
            _Block(0, 5, 5, FLAG_EXISTS),
            _Block(5, 9, 9, FLAG_EXISTS),
            _Block(14, 3, 3, FLAG_EXISTS | FLAG_ENCRYPTED),
        ]
        self.closed = False

    def has_file(self, name: str) -> bool:
        return name.casefold() == "war3map.j"

    def read_file(self, name: str) -> bytes:
        if self.has_file(name):
            return b"named"
        raise KeyError(name)

    def declared_file_size(self, name: str) -> int | None:
        return 5 if self.has_file(name) else None

    def list_files(self) -> list[str]:
        return ["war3map.j"]

    def block_index_of(self, name: str) -> int | None:
        return 0 if self.has_file(name) else None

    def iter_blocks(self) -> tuple[tuple[int, _Block], ...]:
        return tuple(enumerate(self.block_table))

    def read_block_anon(self, block: _Block) -> bytes | None:
        return b"automatic" if block is self.block_table[1] else None

    def read_block_with_key(self, block_index: int, key: int) -> bytes:
        if block_index == 2 and key == 0x1234_5678:
            return b"key-plain"
        return b"wrong"

    def recover_block_key(self, _block: _Block) -> int | None:
        return None

    def peek_block(self, _block: _Block, _size: int = 64) -> bytes:
        return b""

    def close(self) -> None:
        self.closed = True


def _supplemental_file(tmp_path: Path, payload: bytes) -> SupplementalFile:
    path = tmp_path / "war3map.j"
    path.write_bytes(payload)
    digest, identity = sha256_regular_file(path)
    return SupplementalFile(
        "war3map.j",
        path,
        digest,
        len(payload),
        identity,
        1024,
        BlockSource.COMPAT_PLAINTEXT,
    )


def test_plaintext_explicitly_overrides_named_member_and_records_conflict(tmp_path: Path) -> None:
    # Given: verified compatibility plaintext differs from a readable archive member.
    item = _supplemental_file(tmp_path, b"override")
    evidence = SupplementalEvidence("a" * 64, files=(item,))
    archive = SupplementedArchive("source.w3x", _BaseArchive(), evidence)

    # When: the member is read through the unified archive.
    payload = archive.read_file("WAR3MAP.J")

    # Then: explicit plaintext wins and the differing archive content is disclosed.
    assert payload == b"override"
    assert archive.file_source("war3map.j") is BlockSource.COMPAT_PLAINTEXT
    assert "plaintext_override_conflict" in archive.warnings


def test_anonymous_recovery_precedes_verified_compatibility_key() -> None:
    # Given: one block is automatically recoverable and another has a bound key.
    key_plaintext = b"key-plain"
    key = SupplementalKey(
        2,
        0x1234_5678,
        hashlib.sha256(key_plaintext).hexdigest(),
        None,
    )
    base = _BaseArchive()
    archive = SupplementedArchive(
        "source.w3x",
        base,
        SupplementalEvidence("a" * 64, keys=(key,)),
    )

    # When: both anonymous blocks are decoded.
    automatic = archive.read_block_anon_with_source(1, base.block_table[1])
    compatible = archive.read_block_anon_with_source(2, base.block_table[2])

    # Then: their distinct static provenance is retained.
    assert automatic == (b"automatic", BlockSource.ARCHIVE_RECOVERED)
    assert compatible == (key_plaintext, BlockSource.COMPAT_KEY)


def test_wrong_compatibility_key_digest_rejects_complete_bundle() -> None:
    # Given: a key decodes bytes that do not match its declared plaintext digest.
    key = SupplementalKey(2, 0x1234_5678, "b" * 64, None)

    # When/Then: wrong-key garbage never becomes plausible plaintext.
    with pytest.raises(SupplementalEvidenceError, match="plaintext SHA-256 mismatch"):
        _ = SupplementedArchive(
            "source.w3x",
            _BaseArchive(),
            SupplementalEvidence("a" * 64, keys=(key,)),
        )


def test_key_path_must_match_hash_table_block_evidence() -> None:
    # Given: a key claims a named path that maps to another source block.
    key = SupplementalKey(2, 0x1234_5678, hashlib.sha256(b"key-plain").hexdigest(), "war3map.j")

    # When/Then: the false name-to-block claim is rejected before use.
    with pytest.raises(SupplementalEvidenceError, match="path does not match block"):
        _ = SupplementedArchive(
            "source.w3x",
            _BaseArchive(),
            SupplementalEvidence("a" * 64, keys=(key,)),
        )


def test_plaintext_only_overlay_supports_unreadable_container(tmp_path: Path) -> None:
    # Given: no readable MPQ exists but one verified plaintext file does.
    item = _supplemental_file(tmp_path, b"override")
    archive = SupplementedArchive(
        "protected.w3x",
        None,
        SupplementalEvidence("a" * 64, files=(item,)),
    )

    # When/Then: static plaintext remains readable without inventing blocks.
    assert archive.list_files() == ["war3map.j"]
    assert archive.read_file("war3map.j") == b"override"
    assert tuple(archive.iter_blocks()) == ()
