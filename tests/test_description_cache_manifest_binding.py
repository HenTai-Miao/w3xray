"""Owned description-cache source and manifest binding contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.trusted_description_cache_fixture import published_cache
from w3xtool.trusted_description_cache import (
    TrustedDescriptionCacheError,
    load_trusted_description_cache,
)


def test_owned_cache_entry_binds_source_and_owned_manifests(tmp_path: Path) -> None:
    # Given
    root = published_cache(tmp_path)

    # When
    verified = load_trusted_description_cache(root)

    # Then
    entry = verified.cache.entries[0]
    assert entry.source_manifest_sha256 != verified.manifest_sha256
    assert len(entry.source_manifest_sha256) == 64
    assert len(verified.manifest_sha256) == 64


def test_owned_cache_rejects_source_report_hash_tampering(tmp_path: Path) -> None:
    # Given: one original source report changes after publication.
    root = published_cache(tmp_path)
    source_report = next(tmp_path.rglob("对象描述.tsv"))
    source_report.write_bytes(source_report.read_bytes() + b"tampered")

    # When / Then
    with pytest.raises(TrustedDescriptionCacheError):
        load_trusted_description_cache(root)


def test_owned_cache_rejects_manifest_hash_tampering(tmp_path: Path) -> None:
    # Given
    root = published_cache(tmp_path)
    manifest = root / "内容清单.json"
    payload = bytearray(manifest.read_bytes())
    payload[-2] ^= 1
    manifest.write_bytes(payload)

    # When / Then
    with pytest.raises(TrustedDescriptionCacheError):
        load_trusted_description_cache(root)
