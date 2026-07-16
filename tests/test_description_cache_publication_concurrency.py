"""Concurrent-winner tests for owned description-cache publication."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.description_cache_publication_fixture import (
    exchange_in_parent,
    private_publication_paths,
    rename_in_parent,
    replacement_inputs,
)
from tests.trusted_description_cache_fixture import published_cache
from w3xtool import description_cache_publication as publication
from w3xtool.description_cache_migration import (
    DescriptionCacheMigrationOptions,
    migrate_description_cache,
)
from w3xtool.description_cache_publication import (
    DescriptionCacheConcurrentDestinationError,
    DescriptionCachePublicationError,
)
from w3xtool.description_cache_publication_commit import (
    PublicationCommitContextError,
)
from w3xtool.trusted_description_cache import load_trusted_description_cache


def test_foreign_takeover_after_exchange_preserves_previous_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: another writer acquires the output immediately after atomic exchange.
    root = published_cache(tmp_path / "first", raw="first")
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "second")
    displaced_new = root.parent / "concurrent-displaced-new"
    foreign_identities: list[tuple[int, int]] = []

    def takeover_after_exchange(
        parent_descriptor: int,
        source_name: str,
        destination_name: str,
    ) -> None:
        exchange_in_parent(parent_descriptor, source_name, destination_name)
        os.rename(
            destination_name,
            displaced_new.name,
            src_dir_fd=parent_descriptor,
            dst_dir_fd=parent_descriptor,
        )
        root.mkdir()
        _ = (root / "foreign.txt").write_text("foreign", encoding="utf-8")
        status = os.stat(root, follow_symlinks=False)
        foreign_identities.append((status.st_dev, status.st_ino))

    monkeypatch.setattr(
        publication,
        "_rename_exchange",
        takeover_after_exchange,
        raising=False,
    )

    # When: neither the foreign winner nor the old generation can be overwritten.
    with pytest.raises(PublicationCommitContextError, match="NEEDS_CONTEXT"):
        _ = migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, root)
        )

    # Then: the winner remains, while the previous cache survives for recovery.
    assert len(foreign_identities) == 1
    status = os.stat(root, follow_symlinks=False)
    assert (status.st_dev, status.st_ino) == foreign_identities[0]
    assert (root / "foreign.txt").read_text(encoding="utf-8") == "foreign"
    assert not (root / ".w3xray-trusted-description-cache").exists()
    recovery_paths = private_publication_paths(root)
    assert len(recovery_paths) == 1
    recovered = load_trusted_description_cache(recovery_paths[0])
    entry = recovered.cache.lookup("物品", "ratf", "扩展提示", None)[0]
    assert entry.raw_value == "first"
    assert displaced_new.is_dir()


def test_foreign_takeover_before_exchange_is_restored_without_displacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: another writer replaces the verified output immediately before exchange.
    root = published_cache(tmp_path / "first", raw="first")
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "second")
    displaced_previous = root.parent / "concurrent-previous"
    foreign_identities: list[tuple[int, int]] = []
    exchange_count = 0

    def takeover_before_first_exchange(
        parent_descriptor: int,
        source_name: str,
        destination_name: str,
    ) -> None:
        nonlocal exchange_count
        exchange_count += 1
        if exchange_count == 1:
            os.rename(
                destination_name,
                displaced_previous.name,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
            )
            root.mkdir()
            _ = (root / "foreign.txt").write_text("foreign", encoding="utf-8")
            status = os.stat(root, follow_symlinks=False)
            foreign_identities.append((status.st_dev, status.st_ino))
        exchange_in_parent(parent_descriptor, source_name, destination_name)

    monkeypatch.setattr(
        publication,
        "_rename_exchange",
        takeover_before_first_exchange,
        raising=False,
    )

    # When: publication detects that the exchanged object was not the verified cache.
    with pytest.raises(DescriptionCacheConcurrentDestinationError):
        _ = migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, root)
        )

    # Then: an atomic reverse exchange restores the exact concurrent winner.
    assert exchange_count == 2
    assert len(foreign_identities) == 1
    status = os.stat(root, follow_symlinks=False)
    assert (status.st_dev, status.st_ino) == foreign_identities[0]
    assert (root / "foreign.txt").read_text(encoding="utf-8") == "foreign"
    previous = load_trusted_description_cache(displaced_previous)
    entry = previous.cache.lookup("物品", "ratf", "扩展提示", None)[0]
    assert entry.raw_value == "first"
    assert not private_publication_paths(root)


def test_existing_replacement_never_exposes_an_absent_output_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a reader observes the output around the replacement primitive.
    root = published_cache(tmp_path / "first", raw="first")
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "second")
    observations: list[bool] = []

    def observed_exchange(
        parent_descriptor: int,
        source_name: str,
        destination_name: str,
    ) -> None:
        observations.append(root.is_dir())
        exchange_in_parent(parent_descriptor, source_name, destination_name)
        observations.append(root.is_dir())

    monkeypatch.setattr(
        publication,
        "_rename_exchange",
        observed_exchange,
        raising=False,
    )

    # When
    result = migrate_description_cache(
        DescriptionCacheMigrationOptions(legacy_output, legacy_cache, root)
    )

    # Then: one exchange keeps the public name present on both sides.
    assert result.accepted_count == 1
    assert observations == [True, True]
    assert not private_publication_paths(root)


def test_absent_destination_created_before_publish_is_never_replaced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the target is absent during isolation but appears before publication.
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "second")
    output = tmp_path / "concurrent"
    foreign_identities: list[tuple[int, int]] = []

    def create_after_absence(
        parent_descriptor: int,
        source_name: str,
        destination_name: str,
    ) -> None:
        if destination_name == output.name and source_name.startswith(
            ".w3xray-description-cache-stage-"
        ):
            output.mkdir()
            _ = (output / "foreign.txt").write_text("foreign", encoding="utf-8")
            status = os.stat(output, follow_symlinks=False)
            foreign_identities.append((status.st_dev, status.st_ino))
        rename_in_parent(parent_descriptor, source_name, destination_name)

    monkeypatch.setattr(publication, "_rename_noreplace", create_after_absence)

    # When / Then: no-replace rejects the stage and leaves the new owner untouched.
    with pytest.raises(DescriptionCachePublicationError) as raised:
        _ = migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, output)
        )
    assert isinstance(raised.value, DescriptionCacheConcurrentDestinationError)
    assert len(foreign_identities) == 1
    status = os.stat(output, follow_symlinks=False)
    assert (status.st_dev, status.st_ino) == foreign_identities[0]
    assert (output / "foreign.txt").read_text(encoding="utf-8") == "foreign"
    assert not private_publication_paths(output)
