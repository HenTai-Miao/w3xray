"""Deterministic bounded dependency fingerprint contracts."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import w3xtool.batch_dependencies as batch_dependencies
from w3xtool.batch_models import SourceFingerprint
from w3xtool.batch_runner import BatchOptions


def test_dependency_fingerprint_is_stable_and_binds_source_and_cache(
    tmp_path: Path,
) -> None:
    # Given: no game client plus one exact source and trusted-cache digest.
    source = _source()
    options = BatchOptions(str(tmp_path / "maps"), str(tmp_path / "out"))

    # When
    first = batch_dependencies.fingerprint_dependencies(source, options, "b" * 64)
    repeated = batch_dependencies.fingerprint_dependencies(source, options, "b" * 64)
    changed_cache = batch_dependencies.fingerprint_dependencies(
        source, options, "c" * 64
    )

    # Then
    assert first == repeated
    assert len(first) == 64 and first == first.lower()
    assert changed_cache != first


def test_classic_dependency_changes_with_archive_identity(tmp_path: Path) -> None:
    # Given: a classic base MPQ represented by stable size and mtime evidence.
    client = tmp_path / "client"
    client.mkdir()
    archive = client / "war3.mpq"
    archive.write_bytes(b"classic")
    options = _options(tmp_path, client)
    first = batch_dependencies.fingerprint_dependencies(_source(), options, "b" * 64)

    # When: the archive identity changes.
    archive.write_bytes(b"classic-expanded")
    second = batch_dependencies.fingerprint_dependencies(_source(), options, "b" * 64)

    # Then
    assert second != first


def test_casc_dependency_hashes_build_info_and_data_index_stats(tmp_path: Path) -> None:
    # Given: the minimal native-CASC identity surface.
    client = tmp_path / "client"
    data = client / "Data" / "data"
    data.mkdir(parents=True)
    build = client / ".build.info"
    build.write_bytes(b"build=A")
    (data / "data.000").write_bytes(b"data")
    (data / "00.idx").write_bytes(b"index")
    options = _options(tmp_path, client)
    first = batch_dependencies.fingerprint_dependencies(_source(), options, "b" * 64)
    original_mtime = build.stat().st_mtime_ns

    # When: equal-size build metadata changes while its mtime is restored.
    build.write_bytes(b"build=B")
    os.utime(build, ns=(original_mtime, original_mtime))
    second = batch_dependencies.fingerprint_dependencies(_source(), options, "b" * 64)

    # Then: content hashing catches what stat-only evidence would miss.
    assert second != first


def test_extracted_directory_inventory_changes_without_following_symlinks(
    tmp_path: Path,
) -> None:
    # Given: an extracted client directory with one ordinary file.
    client = tmp_path / "client"
    client.mkdir()
    payload = client / "Units.txt"
    payload.write_bytes(b"one")
    options = _options(tmp_path, client)
    first = batch_dependencies.fingerprint_dependencies(_source(), options, "b" * 64)

    # When: the inventory stat changes.
    payload.write_bytes(b"two-two")
    second = batch_dependencies.fingerprint_dependencies(_source(), options, "b" * 64)

    # Then
    assert second != first


def test_dependency_fingerprint_rejects_symlink_root_and_invalid_cache_hash(
    tmp_path: Path,
) -> None:
    # Given: a selected game-data root is a symlink outside the option boundary.
    target = tmp_path / "target"
    target.mkdir()
    (target / "file.txt").write_text("x", encoding="utf-8")
    linked = tmp_path / "linked"
    linked.symlink_to(target, target_is_directory=True)

    # When / Then
    with pytest.raises(batch_dependencies.DependencyFingerprintError):
        batch_dependencies.fingerprint_dependencies(
            _source(),
            _options(tmp_path, linked),
            "invalid",
        )


def _source() -> SourceFingerprint:
    return SourceFingerprint("/maps/sample.w3x", 3, 4, "a" * 64)


def _options(tmp_path: Path, client: Path) -> BatchOptions:
    return BatchOptions(
        str(tmp_path / "maps"),
        str(tmp_path / "out"),
        game_data_path=str(client),
    )
