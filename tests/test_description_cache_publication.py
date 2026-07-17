"""Atomic owned-publication tests for trusted description evidence."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.description_cache_migration_fixture import write_legacy_inputs
from tests.description_cache_publication_fixture import (
    assert_live_retained_records,
    retained_publication_paths,
    replacement_inputs,
    transient_publication_paths,
)
from tests.trusted_description_cache_fixture import published_cache
from w3xtool import description_cache_publication as publication
from w3xtool.description_cache_migration import (
    DescriptionCacheMigrationOptions,
    migrate_description_cache,
)
from w3xtool.description_cache_publication import DescriptionCachePublicationError
from w3xtool.description_cache_publication_commit import (
    PublicationCommitContextError,
)
from w3xtool.durable_io import sync_directory_descriptor
from w3xtool.trusted_description_cache import (
    load_trusted_description_cache,
)


def _exception_chain(error: BaseException) -> tuple[BaseException, ...]:
    pending = [error]
    observed: list[BaseException] = []
    while pending:
        current = pending.pop()
        if any(current is previous for previous in observed):
            continue
        observed.append(current)
        for linked in (current.__cause__, current.__context__):
            if linked is not None:
                pending.append(linked)
    return tuple(observed)


def _assert_current_output_transient(
    error: DescriptionCachePublicationError,
    output: Path,
) -> None:
    current = output.stat(follow_symlinks=False)
    output_evidence = tuple(
        item for item in error.transient if item.leaf_name == output.name
    )
    assert len(output_evidence) == 1
    assert output_evidence[0].identity == (current.st_dev, current.st_ino)
    assert output_evidence[0].held_identity is None


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
    assert len(result.retained) == 1
    assert result.retained[0].role.value == "previous"
    assert_live_retained_records(result.retained)
    assert not transient_publication_paths(root)


def test_failed_replacement_keeps_previous_owned_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a valid owned destination and an atomic exchange failure.
    root = published_cache(tmp_path / "first", raw="first")
    before = load_trusted_description_cache(root)
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "second")
    calls: list[tuple[str, str]] = []
    exchange_fault = OSError("exchange failed")

    def fail_exchange(
        parent_descriptor: int,
        source_name: str,
        destination_name: str,
    ) -> None:
        del parent_descriptor
        calls.append((source_name, destination_name))
        raise exchange_fault

    monkeypatch.setattr(publication, "_rename_exchange", fail_exchange, raising=False)

    # When / Then
    with pytest.raises(PublicationCommitContextError) as raised:
        _ = migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, root)
        )
    assert len(calls) == 1
    assert load_trusted_description_cache(root) == before
    assert type(raised.value) is PublicationCommitContextError
    assert any(current is exchange_fault for current in _exception_chain(raised.value))
    assert raised.value.retained[0].role.value == "failed-stage"
    assert_live_retained_records(raised.value.retained)
    _assert_current_output_transient(raised.value, root)
    assert not transient_publication_paths(root)


def test_sync_failure_after_backup_move_restores_previous_owned_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the old generation has moved aside when parent fsync fails.
    root = published_cache(tmp_path / "first", raw="first")
    before = load_trusted_description_cache(root)
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "second")
    parent_syncs = 0
    sync_fault = OSError("backup sync failed")

    def fail_after_backup(parent_descriptor: int) -> None:
        nonlocal parent_syncs
        parent_syncs += 1
        if parent_syncs == 3:
            raise sync_fault
        sync_directory_descriptor(parent_descriptor)

    monkeypatch.setattr(publication, "_sync_parent", fail_after_backup)

    # When / Then
    with pytest.raises(PublicationCommitContextError) as raised:
        _ = migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, root)
        )
    assert load_trusted_description_cache(root) == before
    assert type(raised.value) is PublicationCommitContextError
    assert any(current is sync_fault for current in _exception_chain(raised.value))
    assert raised.value.retained[0].role.value == "failed-stage"
    assert_live_retained_records(raised.value.retained)
    _assert_current_output_transient(raised.value, root)
    assert not transient_publication_paths(root)


def test_final_parent_sync_failure_preserves_both_generations_and_needs_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the old generation has reached its retained commit name.
    root = published_cache(tmp_path / "first", raw="first")
    before = load_trusted_description_cache(root)
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "second")
    parent_syncs = 0

    def fail_final_sync(parent_descriptor: int) -> None:
        nonlocal parent_syncs
        parent_syncs += 1
        if parent_syncs == 4:
            raise OSError("final parent sync failed")
        sync_directory_descriptor(parent_descriptor)

    monkeypatch.setattr(publication, "_sync_parent", fail_final_sync)

    with pytest.raises(PublicationCommitContextError) as raised:
        _ = migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, root)
        )

    entry = load_trusted_description_cache(root).cache.lookup(
        "物品", "ratf", "扩展提示", None
    )[0]
    assert entry.raw_value == "second"
    assert len(raised.value.retained) == 1
    previous = raised.value.retained[0]
    assert previous.role.value == "previous"
    assert load_trusted_description_cache(previous.path) == before
    assert_live_retained_records(raised.value.retained)
    assert not transient_publication_paths(root)


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
    assert not transient_publication_paths(output)
    assert retained_publication_paths(output)


def test_publication_refuses_regular_file_without_displacing_it(
    tmp_path: Path,
) -> None:
    # Given: a foreign regular file owns the requested output leaf.
    legacy_output, legacy_cache = write_legacy_inputs(tmp_path / "input")
    output = tmp_path / "foreign-file"
    _ = output.write_text("foreign", encoding="utf-8")
    before = output.stat(follow_symlinks=False)

    # When / Then
    with pytest.raises(DescriptionCachePublicationError, match="not a directory"):
        _ = migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, output)
        )
    after = output.stat(follow_symlinks=False)
    assert (after.st_dev, after.st_ino) == (before.st_dev, before.st_ino)
    assert output.read_text(encoding="utf-8") == "foreign"
    assert not transient_publication_paths(output)
    assert retained_publication_paths(output)
