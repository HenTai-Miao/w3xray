"""Atomic owned-publication tests for trusted description evidence."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.description_cache_migration_fixture import write_legacy_inputs
from tests.description_cache_publication_fixture import (
    private_publication_paths,
    rename_in_parent,
    replacement_inputs,
)
from tests.trusted_description_cache_fixture import published_cache
from w3xtool import description_cache_publication as publication
from w3xtool import description_cache_publication_transaction as transaction
from w3xtool.description_cache_migration import (
    DescriptionCacheMigrationOptions,
    migrate_description_cache,
)
from w3xtool.description_cache_publication import DescriptionCachePublicationError
from w3xtool.description_cache_publication_commit import (
    PublicationCommitContextError,
)
from w3xtool.description_cache_owned_schema import (
    TRUSTED_DESCRIPTION_CACHE_MARKER,
)
from w3xtool.durable_io import sync_directory_descriptor
from w3xtool.trusted_description_cache import (
    TrustedDescriptionCacheError,
    VerifiedDescriptionCache,
    load_trusted_description_cache,
)


def test_owned_cache_replacement_publishes_new_valid_generation(tmp_path: Path) -> None:
    # Given: one valid owned cache and independently proven replacement evidence.
    root = published_cache(tmp_path / "first", raw="first")
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "second")

    # When
    result = migrate_description_cache(
        DescriptionCacheMigrationOptions(legacy_output, legacy_cache, root)
    )

    # Then
    assert result.accepted_count == 1
    entry = load_trusted_description_cache(root).cache.lookup(
        "物品", "ratf", "扩展提示", None
    )[0]
    assert entry.raw_value == "second"
    assert not private_publication_paths(root)


def test_failed_replacement_keeps_previous_owned_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a valid owned destination and a stage-to-destination rename failure.
    root = published_cache(tmp_path / "first", raw="first")
    before = load_trusted_description_cache(root)
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "second")
    calls: list[tuple[str, str]] = []

    def fail_replace(
        parent_descriptor: int,
        source_name: str,
        destination_name: str,
    ) -> None:
        if "-stage-" in source_name:
            calls.append((source_name, destination_name))
            raise OSError("replace failed")
        rename_in_parent(parent_descriptor, source_name, destination_name)

    monkeypatch.setattr(publication, "_rename_noreplace", fail_replace)

    # When / Then
    with pytest.raises(DescriptionCachePublicationError, match="replace failed"):
        _ = migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, root)
        )
    assert len(calls) == 1
    assert load_trusted_description_cache(root) == before
    assert not private_publication_paths(root)


def test_sync_failure_after_backup_move_restores_previous_owned_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the old generation has moved aside when parent fsync fails.
    root = published_cache(tmp_path / "first", raw="first")
    before = load_trusted_description_cache(root)
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "second")
    parent_syncs = 0

    def fail_after_backup(parent_descriptor: int) -> None:
        nonlocal parent_syncs
        parent_syncs += 1
        if parent_syncs == 1:
            raise OSError("backup sync failed")
        sync_directory_descriptor(parent_descriptor)

    monkeypatch.setattr(publication, "_sync_parent", fail_after_backup)

    # When / Then
    with pytest.raises(DescriptionCachePublicationError, match="backup sync failed"):
        _ = migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, root)
        )
    assert load_trusted_description_cache(root) == before
    assert not private_publication_paths(root)


def test_backup_removal_failure_restores_previous_owned_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the new generation is valid while the intact backup cannot be removed.
    root = published_cache(tmp_path / "first", raw="first")
    before = load_trusted_description_cache(root)
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "second")
    remove_directory = getattr(transaction, "_remove_directory")

    def fail_backup_removal(
        parent_descriptor: int,
        name: str,
        expected: tuple[int, int],
    ) -> None:
        if "-backup-" in name:
            raise OSError("backup removal failed")
        remove_directory(parent_descriptor, name, expected)

    monkeypatch.setattr(transaction, "_remove_directory", fail_backup_removal)

    # When / Then: the still-recoverable old generation is restored exactly once.
    with pytest.raises(DescriptionCachePublicationError, match="backup removal failed"):
        _ = migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, root)
        )
    assert load_trusted_description_cache(root) == before
    assert not private_publication_paths(root)


def test_partial_backup_removal_keeps_unprovable_output_for_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: cleanup partially damages the old backup and the new output is invalid.
    root = published_cache(tmp_path / "first", raw="first")
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "second")
    remove_directory = getattr(transaction, "_remove_directory")
    output_identities: list[tuple[int, int]] = []

    def damage_backup_then_fail(
        parent_descriptor: int,
        name: str,
        expected: tuple[int, int],
    ) -> None:
        if "-backup-" not in name:
            remove_directory(parent_descriptor, name, expected)
            return
        backup = root.parent / name
        (backup / TRUSTED_DESCRIPTION_CACHE_MARKER).unlink()
        (root / TRUSTED_DESCRIPTION_CACHE_MARKER).unlink()
        details = root.stat(follow_symlinks=False)
        output_identities.append((details.st_dev, details.st_ino))
        raise OSError("backup partially removed")

    monkeypatch.setattr(transaction, "_remove_directory", damage_backup_then_fail)

    # When: rollback cannot prove either generation safe enough to replace the other.
    with pytest.raises(PublicationCommitContextError, match="NEEDS_CONTEXT"):
        _ = migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, root)
        )

    # Then: the unprovable output survives byte-for-byte recovery by an operator.
    assert len(output_identities) == 1
    details = root.stat(follow_symlinks=False)
    assert (details.st_dev, details.st_ino) == output_identities[0]
    with pytest.raises(TrustedDescriptionCacheError):
        _ = load_trusted_description_cache(root)
    backups = tuple(
        path for path in private_publication_paths(root) if "-backup-" in path.name
    )
    assert len(backups) == 1
    assert not (backups[0] / TRUSTED_DESCRIPTION_CACHE_MARKER).exists()


def test_final_parent_sync_failure_after_backup_removal_returns_committed_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the old generation is gone when the final parent fsync fails.
    root = published_cache(tmp_path / "first", raw="first")
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "second")
    parent_syncs = 0

    def fail_final_sync(parent_descriptor: int) -> None:
        nonlocal parent_syncs
        parent_syncs += 1
        if parent_syncs == 3:
            raise OSError("final parent sync failed")
        sync_directory_descriptor(parent_descriptor)

    monkeypatch.setattr(publication, "_sync_parent", fail_final_sync)

    # When: publication crosses its irreversible commit point before the error.
    result = migrate_description_cache(
        DescriptionCacheMigrationOptions(legacy_output, legacy_cache, root)
    )

    # Then: it does not report a rollback-style failure after deleting the backup.
    assert result.accepted_count == 1
    entry = load_trusted_description_cache(root).cache.lookup(
        "物品", "ratf", "扩展提示", None
    )[0]
    assert entry.raw_value == "second"
    assert not private_publication_paths(root)


def test_stage_self_validation_failure_keeps_destination_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a valid destination and a staged generation that fails validation.
    root = published_cache(tmp_path / "first", raw="first")
    before = load_trusted_description_cache(root)
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "second")

    def reject_stage(path: Path) -> VerifiedDescriptionCache:
        if path.name.startswith(".w3xray-description-cache-stage-"):
            raise DescriptionCachePublicationError("stage validation failed")
        return load_trusted_description_cache(path)

    monkeypatch.setattr(publication, "_require_valid", reject_stage)

    # When / Then
    with pytest.raises(DescriptionCachePublicationError, match="stage validation"):
        _ = migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, root)
        )
    assert load_trusted_description_cache(root) == before
    assert not private_publication_paths(root)


def test_failed_replacement_validation_restores_previous_owned_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: stage validation passes, but validation after replacement fails.
    root = published_cache(tmp_path / "first", raw="first")
    before = load_trusted_description_cache(root)
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "second")
    destination_validations = 0

    def reject_replaced_destination(path: Path) -> VerifiedDescriptionCache:
        nonlocal destination_validations
        if path == root:
            destination_validations += 1
            if destination_validations == 1:
                raise DescriptionCachePublicationError("replacement validation failed")
        return load_trusted_description_cache(path)

    monkeypatch.setattr(
        publication,
        "_require_valid",
        reject_replaced_destination,
    )

    # When / Then
    with pytest.raises(
        DescriptionCachePublicationError, match="replacement validation"
    ):
        _ = migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, root)
        )
    assert load_trusted_description_cache(root) == before
    assert not private_publication_paths(root)


def test_publication_refuses_unowned_existing_destination(tmp_path: Path) -> None:
    # Given: an existing foreign directory at the requested destination.
    legacy_output, legacy_cache = write_legacy_inputs(tmp_path / "input")
    output = tmp_path / "foreign"
    output.mkdir()
    foreign = output / "keep.txt"
    _ = foreign.write_text("foreign", encoding="utf-8")

    # When / Then
    with pytest.raises(DescriptionCachePublicationError, match="owned|valid"):
        _ = migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, output)
        )
    assert foreign.read_text(encoding="utf-8") == "foreign"
    assert not private_publication_paths(output)
