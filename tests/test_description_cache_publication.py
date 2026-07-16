"""Atomic owned-publication tests for trusted description evidence."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.description_cache_migration_fixture import (
    candidate,
    legacy_client_fill,
    write_legacy_inputs,
)
from tests.trusted_description_cache_fixture import published_cache
from w3xtool import description_cache_publication as publication
from w3xtool.description_cache_migration import (
    DescriptionCacheMigrationOptions,
    migrate_description_cache,
)
from w3xtool.description_cache_publication import DescriptionCachePublicationError
from w3xtool.trusted_description_cache import (
    VerifiedDescriptionCache,
    load_trusted_description_cache,
)


def test_owned_cache_replacement_publishes_new_valid_generation(tmp_path: Path) -> None:
    # Given: one valid owned cache and independently proven replacement evidence.
    root = published_cache(tmp_path / "first", raw="first")
    legacy_output, legacy_cache = _replacement_inputs(tmp_path, "second")

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
    assert not _private_publication_paths(root)


def test_failed_replacement_keeps_previous_owned_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a valid owned destination and a stage-to-destination rename failure.
    root = published_cache(tmp_path / "first", raw="first")
    before = load_trusted_description_cache(root)
    legacy_output, legacy_cache = _replacement_inputs(tmp_path, "second")
    calls: list[tuple[Path, Path]] = []

    def fail_replace(stage: Path, destination: Path) -> None:
        calls.append((stage, destination))
        raise OSError("replace failed")

    monkeypatch.setattr(publication, "_replace_stage", fail_replace, raising=False)

    # When / Then
    with pytest.raises(DescriptionCachePublicationError, match="replace failed"):
        migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, root)
        )
    assert len(calls) == 1
    assert load_trusted_description_cache(root) == before
    assert not _private_publication_paths(root)


def test_sync_failure_after_backup_move_restores_previous_owned_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the old generation has moved aside when parent fsync fails.
    root = published_cache(tmp_path / "first", raw="first")
    before = load_trusted_description_cache(root)
    legacy_output, legacy_cache = _replacement_inputs(tmp_path, "second")
    sync_directory = publication.sync_directory
    parent_syncs = 0

    def fail_after_backup(path: Path) -> None:
        nonlocal parent_syncs
        if path == root.parent:
            parent_syncs += 1
            if parent_syncs == 2:
                raise OSError("backup sync failed")
        sync_directory(path)

    monkeypatch.setattr(publication, "sync_directory", fail_after_backup)

    # When / Then
    with pytest.raises(DescriptionCachePublicationError, match="backup sync failed"):
        migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, root)
        )
    assert load_trusted_description_cache(root) == before
    assert not _private_publication_paths(root)


def test_stage_self_validation_failure_keeps_destination_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a valid destination and a staged generation that fails validation.
    root = published_cache(tmp_path / "first", raw="first")
    before = load_trusted_description_cache(root)
    legacy_output, legacy_cache = _replacement_inputs(tmp_path, "second")
    require_valid = publication._require_valid

    def reject_stage(path: Path) -> VerifiedDescriptionCache:
        if path.name.startswith(".w3xray-description-cache-stage-"):
            raise DescriptionCachePublicationError("stage validation failed")
        return require_valid(path)

    monkeypatch.setattr(publication, "_require_valid", reject_stage)

    # When / Then
    with pytest.raises(DescriptionCachePublicationError, match="stage validation"):
        migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, root)
        )
    assert load_trusted_description_cache(root) == before
    assert not _private_publication_paths(root)


def test_failed_replacement_validation_restores_previous_owned_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: stage validation passes, but validation after replacement fails.
    root = published_cache(tmp_path / "first", raw="first")
    before = load_trusted_description_cache(root)
    legacy_output, legacy_cache = _replacement_inputs(tmp_path, "second")
    require_valid = publication._require_valid
    destination_validations = 0

    def reject_replaced_destination(path: Path) -> VerifiedDescriptionCache:
        nonlocal destination_validations
        if path == root:
            destination_validations += 1
            if destination_validations == 2:
                raise DescriptionCachePublicationError("replacement validation failed")
        return require_valid(path)

    monkeypatch.setattr(
        publication,
        "_require_valid",
        reject_replaced_destination,
    )

    # When / Then
    with pytest.raises(
        DescriptionCachePublicationError, match="replacement validation"
    ):
        migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, root)
        )
    assert load_trusted_description_cache(root) == before
    assert not _private_publication_paths(root)


def test_publication_refuses_unowned_existing_destination(tmp_path: Path) -> None:
    # Given: an existing foreign directory at the requested destination.
    legacy_output, legacy_cache = write_legacy_inputs(tmp_path / "input")
    output = tmp_path / "foreign"
    output.mkdir()
    foreign = output / "keep.txt"
    foreign.write_text("foreign", encoding="utf-8")

    # When / Then
    with pytest.raises(DescriptionCachePublicationError, match="owned|valid"):
        migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, output)
        )
    assert foreign.read_text(encoding="utf-8") == "foreign"
    assert not _private_publication_paths(output)


def _replacement_inputs(root: Path, raw: str) -> tuple[Path, Path]:
    return write_legacy_inputs(
        root / "replacement",
        cache_rows=(candidate(raw=raw),),
        report_rows=(
            legacy_client_fill(
                raw_description=raw,
                readable_description=raw,
            ),
        ),
    )


def _private_publication_paths(output: Path) -> tuple[Path, ...]:
    patterns = (
        ".w3xray-description-cache-stage-*",
        ".w3xray-description-cache-backup-*",
    )
    return tuple(path for pattern in patterns for path in output.parent.glob(pattern))
