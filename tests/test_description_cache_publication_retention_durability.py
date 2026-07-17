"""Durability and parent-binding proof for retained generations."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.description_cache_publication_fixture import replacement_inputs
from tests.trusted_description_cache_fixture import published_cache
from w3xtool import description_cache_publication as publication
from w3xtool import description_cache_publication_parent as publication_parent
from w3xtool.description_cache_migration import (
    DescriptionCacheMigrationOptions,
    migrate_description_cache,
)
from w3xtool.description_cache_publication_errors import (
    PublicationCommitContextError,
)
from w3xtool.description_cache_publication_models import RetainedCacheRecord
from w3xtool.durable_io import sync_directory_descriptor
from w3xtool.trusted_description_cache import (
    VerifiedDescriptionCache,
    load_trusted_description_cache,
)


def _identity(path: Path) -> tuple[int, int]:
    details = path.stat(follow_symlinks=False)
    return details.st_dev, details.st_ino


def _assert_live(records: tuple[RetainedCacheRecord, ...]) -> None:
    for record in records:
        assert _identity(record.path) == record.identity


def test_previous_install_sync_failure_never_rolls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = published_cache(tmp_path / "first", raw="first")
    previous_identity = _identity(output)
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "second")
    syncs = 0
    exchanges = 0
    real_exchange = getattr(publication, "_rename_exchange")

    def count_exchange(descriptor: int, source: str, target: str) -> None:
        nonlocal exchanges
        exchanges += 1
        real_exchange(descriptor, source, target)

    def fail_commit_sync(descriptor: int) -> None:
        nonlocal syncs
        syncs += 1
        if syncs == 4:
            raise OSError("previous retention sync failed")
        sync_directory_descriptor(descriptor)

    monkeypatch.setattr(publication, "_rename_exchange", count_exchange)
    monkeypatch.setattr(publication, "_sync_parent", fail_commit_sync)
    with pytest.raises(PublicationCommitContextError) as raised:
        migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, output)
        )

    assert exchanges == 1
    assert (
        load_trusted_description_cache(output)
        .cache.lookup("物品", "ratf", "扩展提示", None)[0]
        .raw_value
        == "second"
    )
    assert len(raised.value.retained) == 1
    assert raised.value.retained[0].identity == previous_identity
    _assert_live(raised.value.retained)


def test_failed_output_retention_sync_failure_keeps_live_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "first")
    output = tmp_path / "trusted"
    original = getattr(publication, "_require_valid_at")
    syncs = 0

    def reject_output(descriptor: int, path: Path) -> VerifiedDescriptionCache:
        if path == output:
            raise OSError("output rejected")
        return original(descriptor, path)

    def fail_retention_sync(descriptor: int) -> None:
        nonlocal syncs
        syncs += 1
        if syncs == 3:
            raise OSError("failed-output sync failed")
        sync_directory_descriptor(descriptor)

    monkeypatch.setattr(publication, "_require_valid_at", reject_output)
    monkeypatch.setattr(publication, "_sync_parent", fail_retention_sync)
    with pytest.raises(PublicationCommitContextError) as raised:
        migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, output)
        )

    assert any(row.role.value == "failed-output" for row in raised.value.retained)
    _assert_live(raised.value.retained)


def test_failed_stage_retention_sync_failure_keeps_live_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = published_cache(tmp_path / "first", raw="first")
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "second")
    original = getattr(publication, "_require_valid_at")

    def reject_stage(descriptor: int, path: Path) -> VerifiedDescriptionCache:
        if path.name.startswith(".w3xray-description-cache-stage-"):
            raise OSError("stage rejected")
        return original(descriptor, path)

    def fail_sync(_descriptor: int) -> None:
        raise OSError("failed-stage sync failed")

    monkeypatch.setattr(publication, "_require_valid_at", reject_stage)
    monkeypatch.setattr(publication, "_sync_parent", fail_sync)
    with pytest.raises(PublicationCommitContextError) as raised:
        migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, output)
        )

    assert any(row.role.value == "failed-stage" for row in raised.value.retained)
    _assert_live(raised.value.retained)


def test_parent_loss_after_retention_demotes_record_to_transient(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = published_cache(tmp_path / "first", raw="first")
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "second")
    displaced_parent = tmp_path / "held-parent"
    original = publication_parent.require_parent_identity
    checks = 0

    def lose_parent(descriptor: int, parent: Path, expected: tuple[int, int]) -> None:
        nonlocal checks
        checks += 1
        original(descriptor, parent, expected)
        if checks == 11:
            parent.rename(displaced_parent)
            parent.mkdir()

    monkeypatch.setattr(publication_parent, "require_parent_identity", lose_parent)
    with pytest.raises(PublicationCommitContextError) as raised:
        migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, output)
        )

    assert raised.value.retained == ()
    assert raised.value.transient
    assert not tuple(output.parent.glob(".w3xray-description-cache-retained-*-*"))
    assert tuple(displaced_parent.glob(".w3xray-description-cache-retained-*-*"))
