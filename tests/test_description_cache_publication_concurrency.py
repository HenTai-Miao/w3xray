"""Concurrent-winner tests for owned description-cache publication."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.description_cache_publication_fixture import (
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


def test_existing_destination_recreated_after_isolation_is_never_deleted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a valid destination is isolated, then another writer owns its name.
    root = published_cache(tmp_path / "first", raw="first")
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "second")
    foreign_identities: list[tuple[int, int]] = []

    def recreate_after_isolation(
        parent_descriptor: int,
        source_name: str,
        destination_name: str,
    ) -> None:
        rename_in_parent(parent_descriptor, source_name, destination_name)
        if source_name == root.name and "-backup-" in destination_name:
            root.mkdir()
            _ = (root / "foreign.txt").write_text("foreign", encoding="utf-8")
            status = os.stat(root, follow_symlinks=False)
            foreign_identities.append((status.st_dev, status.st_ino))

    monkeypatch.setattr(publication, "_rename_noreplace", recreate_after_isolation)

    # When / Then: the external winner survives and this stage never publishes.
    with pytest.raises(DescriptionCachePublicationError) as raised:
        _ = migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, root)
        )
    assert isinstance(raised.value, DescriptionCacheConcurrentDestinationError)
    assert len(foreign_identities) == 1
    status = os.stat(root, follow_symlinks=False)
    assert (status.st_dev, status.st_ino) == foreign_identities[0]
    assert (root / "foreign.txt").read_text(encoding="utf-8") == "foreign"
    assert not (root / ".w3xray-trusted-description-cache").exists()
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
        try:
            rename_in_parent(parent_descriptor, source_name, destination_name)
        except FileNotFoundError:
            if source_name == output.name and "-backup-" in destination_name:
                output.mkdir()
                _ = (output / "foreign.txt").write_text("foreign", encoding="utf-8")
                status = os.stat(output, follow_symlinks=False)
                foreign_identities.append((status.st_dev, status.st_ino))
            raise

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
