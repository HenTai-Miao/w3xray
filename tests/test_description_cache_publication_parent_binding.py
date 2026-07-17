"""Parent-binding failures around trusted-cache publication commit."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.description_cache_publication_fixture import (
    assert_live_retained_records,
    replacement_inputs,
    transient_publication_paths,
)
from tests.trusted_description_cache_fixture import published_cache
from w3xtool import description_cache_publication as publication
from w3xtool import description_cache_publication_parent as publication_parent
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
    VerifiedDescriptionCache,
    load_trusted_description_cache,
)


def test_transient_parent_aba_cannot_authorize_held_foreign_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: every validation sees a valid substitute parent only between its checks.
    parent = tmp_path / "publication"
    parent.mkdir()
    output = parent / "trusted"
    output.mkdir()
    sentinel = output / "keep.txt"
    sentinel.write_text("foreign", encoding="utf-8")
    before = output.stat(follow_symlinks=False)
    held_parent = tmp_path / "held-publication"
    substitute = published_cache(tmp_path / "validation-target", raw="other")
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "second")
    original_parent_check = publication_parent.require_parent_identity
    original_require_valid = publication_parent.ParentBoundValidator.require_valid
    active_name: str | None = None
    parent_is_swapped = False
    swap_count = 0

    def require_valid_during_aba(
        validator: publication_parent.ParentBoundValidator,
        path: Path,
    ) -> VerifiedDescriptionCache:
        nonlocal active_name, parent_is_swapped
        active_name = path.name
        try:
            return original_require_valid(validator, path)
        finally:
            if parent_is_swapped:
                (parent / path.name).rename(substitute)
                parent.rmdir()
                held_parent.rename(parent)
                parent_is_swapped = False
            active_name = None

    def replace_parent_between_checks(
        parent_descriptor: int,
        named_parent: Path,
        expected: tuple[int, int],
    ) -> None:
        nonlocal parent_is_swapped, swap_count
        if active_name is None:
            original_parent_check(parent_descriptor, named_parent, expected)
            return
        if not parent_is_swapped:
            original_parent_check(parent_descriptor, named_parent, expected)
            parent.rename(held_parent)
            parent.mkdir()
            substitute.rename(parent / active_name)
            parent_is_swapped = True
            swap_count += 1
            return
        (parent / active_name).rename(substitute)
        parent.rmdir()
        held_parent.rename(parent)
        parent_is_swapped = False
        original_parent_check(parent_descriptor, named_parent, expected)

    monkeypatch.setattr(
        publication_parent.ParentBoundValidator,
        "require_valid",
        require_valid_during_aba,
    )
    monkeypatch.setattr(
        publication_parent,
        "require_parent_identity",
        replace_parent_between_checks,
    )

    # When: publication must validate the held foreign leaf, not substitute bytes.
    with pytest.raises(DescriptionCachePublicationError):
        _ = migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, output)
        )

    # Then: repeated ABA never authorizes exchange or removal of the sentinel.
    assert swap_count >= 1
    after = output.stat(follow_symlinks=False)
    assert (after.st_dev, after.st_ino) == (before.st_dev, before.st_ino)
    assert sentinel.read_text(encoding="utf-8") == "foreign"


def test_parent_swap_during_validation_preserves_held_foreign_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the held publication parent contains an unowned destination sentinel.
    parent = tmp_path / "publication"
    parent.mkdir()
    output = parent / "trusted"
    output.mkdir()
    sentinel = output / "keep.txt"
    sentinel.write_text("foreign", encoding="utf-8")
    before = output.stat(follow_symlinks=False)
    held_parent = tmp_path / "held-publication"
    replacement = published_cache(tmp_path / "validation-target", raw="other")
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "second")
    require_valid_at = getattr(publication, "_require_valid_at")
    swapped = False

    def swap_parent_during_validation(
        parent_descriptor: int,
        path: Path,
    ) -> VerifiedDescriptionCache:
        nonlocal swapped
        if path == output and not swapped:
            swapped = True
            parent.rename(held_parent)
            parent.mkdir()
            replacement.rename(output)
        return require_valid_at(parent_descriptor, path)

    monkeypatch.setattr(
        publication,
        "_require_valid_at",
        swap_parent_during_validation,
    )

    # When: pathname validation reopens a replacement parent during the transaction.
    with pytest.raises(PublicationCommitContextError, match="NEEDS_CONTEXT"):
        _ = migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, output)
        )

    # Then: no exchange or cleanup displaces the object below the held parent.
    assert swapped
    held_output = held_parent / output.name
    after = held_output.stat(follow_symlinks=False)
    assert (after.st_dev, after.st_ino) == (before.st_dev, before.st_ino)
    assert (held_output / sentinel.name).read_text(encoding="utf-8") == "foreign"
    replacement_entry = load_trusted_description_cache(output).cache.lookup(
        "物品", "ratf", "扩展提示", None
    )[0]
    assert replacement_entry.raw_value == "other"


def test_post_commit_output_replacement_is_typed_needs_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: final sync will fail after backup deletion and replace the committed name.
    root = published_cache(tmp_path / "first", raw="first")
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "second")
    displaced = root.parent / "committed-output"
    parent_syncs = 0
    backups_at_failure: list[Path] = []

    def replace_output_during_final_sync(parent_descriptor: int) -> None:
        nonlocal parent_syncs
        parent_syncs += 1
        if parent_syncs != 4:
            sync_directory_descriptor(parent_descriptor)
            return
        backups_at_failure.extend(
            path
            for path in transient_publication_paths(root)
            if "-backup-" in path.name
        )
        os.rename(
            root.name,
            displaced.name,
            src_dir_fd=parent_descriptor,
            dst_dir_fd=parent_descriptor,
        )
        descriptor = os.open(
            root.name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
            dir_fd=parent_descriptor,
        )
        try:
            _ = os.write(descriptor, b"foreign")
        finally:
            os.close(descriptor)
        raise OSError("final parent sync failed")

    monkeypatch.setattr(publication, "_sync_parent", replace_output_during_final_sync)

    # When / Then: every post-commit proof loss uses the typed recovery contract.
    with pytest.raises(PublicationCommitContextError, match="NEEDS_CONTEXT") as raised:
        _ = migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, root)
        )
    assert backups_at_failure == []
    assert root.read_text(encoding="utf-8") == "foreign"
    entry = load_trusted_description_cache(displaced).cache.lookup(
        "物品", "ratf", "扩展提示", None
    )[0]
    assert entry.raw_value == "second"
    assert any(record.role.value == "previous" for record in raised.value.retained)
    assert_live_retained_records(raised.value.retained)
