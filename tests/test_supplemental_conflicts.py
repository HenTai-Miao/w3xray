"""Conflict rejection while normalizing independent supplemental sources."""

from __future__ import annotations

from pathlib import Path

import pytest

from w3xtool.author_plaintext_bundle import AuthorBundleFile, AuthorPlaintextBundle
from w3xtool.bounded_file import FileIdentity, sha256_regular_file
from w3xtool.extraction_ledger import BlockSource
from w3xtool.supplemental_evidence import (
    SupplementalEvidence,
    SupplementalEvidenceError,
    SupplementalFile,
    SupplementalKey,
    evidence_from_author_bundle,
    merge_supplemental_evidence,
)


_SHA = "a" * 64


def _file(name: str, source: BlockSource) -> SupplementalFile:
    return SupplementalFile(
        name=name,
        path=Path(name),
        sha256=_SHA,
        size=1,
        identity=FileIdentity(1, 2, 1),
        max_bytes=1,
        source=source,
    )


def _evidence(
    *,
    names: tuple[str, ...] = (),
    files: tuple[SupplementalFile, ...] = (),
    keys: tuple[SupplementalKey, ...] = (),
) -> SupplementalEvidence:
    return SupplementalEvidence(_SHA, names, files, keys)


def test_merge_rejects_path_conflict_across_sources() -> None:
    # Given: author and compatibility evidence claim one normalized MPQ path.
    author = _evidence(files=(_file("UI\\Main.fdf", BlockSource.AUTHOR_PLAINTEXT),))
    compat = _evidence(files=(_file("ui/main.fdf", BlockSource.COMPAT_PLAINTEXT),))

    # When/Then: loading order cannot select the winner.
    with pytest.raises(SupplementalEvidenceError, match="path conflict"):
        _ = merge_supplemental_evidence(author, compat)


def test_merge_rejects_key_conflict_across_sources() -> None:
    # Given: two evidence sets declare a final key for the same block.
    key = SupplementalKey(7, 0x12345678, _SHA, None)

    # When/Then: block ownership must be unique.
    with pytest.raises(SupplementalEvidenceError, match="block conflict"):
        _ = merge_supplemental_evidence(
            _evidence(keys=(key,)),
            _evidence(keys=(key,)),
        )


def test_merge_preserves_distinct_evidence_in_source_order() -> None:
    # Given: independent author plaintext and compatibility key evidence.
    author = _evidence(files=(_file("war3map.j", BlockSource.AUTHOR_PLAINTEXT),))
    compat_key = SupplementalKey(7, 0x12345678, _SHA, None)
    compat = _evidence(names=("war3map.wts",), keys=(compat_key,))

    # When: both sources are normalized.
    merged = merge_supplemental_evidence(author, compat)

    # Then: all non-conflicting evidence remains available deterministically.
    assert merged is not None
    assert merged.files == author.files
    assert merged.names == ("war3map.wts",)
    assert merged.keys == (compat_key,)


def test_author_bundle_normalizes_to_verified_supplemental_file(tmp_path: Path) -> None:
    # Given: the legacy author bundle already pinned one plaintext identity.
    path = tmp_path / "war3map.j"
    path.write_bytes(b"x")
    digest, identity = sha256_regular_file(path)
    author = AuthorPlaintextBundle(
        _SHA,
        (AuthorBundleFile("war3map.j", path, digest, 1, identity),),
    )

    # When: the legacy source enters the unified supplemental model.
    normalized = evidence_from_author_bundle(author)

    # Then: its provenance and identity-preserving read remain explicit.
    assert normalized.files[0].source is BlockSource.AUTHOR_PLAINTEXT
    assert normalized.files[0].read() == b"x"
