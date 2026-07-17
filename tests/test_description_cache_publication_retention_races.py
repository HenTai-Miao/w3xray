"""Namespace takeover races around retained cache publication."""

from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path

import pytest

from tests.description_cache_publication_fixture import (
    exchange_in_parent,
    rename_in_parent,
    replacement_inputs,
)
from tests.trusted_description_cache_fixture import published_cache
from w3xtool import description_cache_publication as publication
from w3xtool import description_cache_publication_retention as retention
from w3xtool.description_cache_migration import (
    DescriptionCacheMigrationOptions,
    migrate_description_cache,
)
from w3xtool.description_cache_publication_errors import (
    DescriptionCachePublicationError,
    PublicationCommitContextError,
)
from w3xtool.description_cache_publication_models import (
    RetainedCacheRecord,
    RetainedCacheRole,
)
from w3xtool.description_cache_publication_retention_names import RetainedCacheNames
from w3xtool.trusted_description_cache import load_trusted_description_cache


type ObjectFactory = Callable[[Path], str | None]
_DIRECTORY_FLAGS = (
    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
)


def _identity(path: Path) -> tuple[int, int]:
    details = path.stat(follow_symlinks=False)
    return details.st_dev, details.st_ino


def _assert_live(records: tuple[RetainedCacheRecord, ...]) -> None:
    for record in records:
        assert _identity(record.path) == record.identity


def _regular_file(path: Path) -> str | None:
    path.write_text("foreign", encoding="utf-8")
    return None


def _dangling_symlink(path: Path) -> str:
    target = "deliberately-absent"
    path.symlink_to(target)
    return target


def test_retention_race_preserves_expected_and_foreign_objects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = published_cache(tmp_path / "first", raw="first")
    previous_identity = _identity(output)
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "second")
    displaced_previous = output.parent / "displaced-previous"
    decoy = output.parent / "retention-decoy"
    decoy.mkdir()
    decoy_identity = _identity(decoy)
    original = getattr(publication, "_rename_noreplace")
    raced = False

    def race(descriptor: int, source_name: str, target_name: str) -> None:
        nonlocal raced
        if not raced and target_name.endswith("-previous"):
            raced = True
            os.rename(
                source_name,
                displaced_previous.name,
                src_dir_fd=descriptor,
                dst_dir_fd=descriptor,
            )
            os.rename(
                decoy.name,
                source_name,
                src_dir_fd=descriptor,
                dst_dir_fd=descriptor,
            )
        original(descriptor, source_name, target_name)

    monkeypatch.setattr(publication, "_rename_noreplace", race)
    with pytest.raises(PublicationCommitContextError) as raised:
        migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, output)
        )

    assert raced and _identity(displaced_previous) == previous_identity
    assert any(
        row.role.value == "recovery" and row.identity == decoy_identity
        for row in raised.value.retained
    )
    _assert_live(raised.value.retained)


def test_absent_move_then_raise_keeps_commit_subtype_after_retention(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "first")
    output = tmp_path / "trusted"
    original = getattr(publication, "_rename_noreplace")
    move_fault = RuntimeError("injected after absent-output install")
    injected = False

    def move_then_raise(descriptor: int, source_name: str, target_name: str) -> None:
        nonlocal injected
        original(descriptor, source_name, target_name)
        if target_name == output.name and not injected:
            injected = True
            raise move_fault

    monkeypatch.setattr(publication, "_rename_noreplace", move_then_raise)
    with pytest.raises(DescriptionCachePublicationError) as raised:
        migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, output)
        )

    assert injected and type(raised.value) is PublicationCommitContextError
    assert any(failure is move_fault for failure in raised.value.failures)
    assert not output.exists() and len(raised.value.retained) == 1
    assert raised.value.retained[0].role.value == "failed-output"
    _assert_live(raised.value.retained)


def test_output_takeover_after_exchange_retains_exact_previous(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = published_cache(tmp_path / "first", raw="first")
    previous_identity = _identity(output)
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "second")
    displaced_new = output.parent / "displaced-new"

    def takeover(descriptor: int, source_name: str, target_name: str) -> None:
        exchange_in_parent(descriptor, source_name, target_name)
        os.rename(
            target_name,
            displaced_new.name,
            src_dir_fd=descriptor,
            dst_dir_fd=descriptor,
        )
        output.mkdir()
        (output / "foreign.txt").write_text("foreign", encoding="utf-8")

    monkeypatch.setattr(publication, "_rename_exchange", takeover)
    with pytest.raises(PublicationCommitContextError) as raised:
        migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, output)
        )

    assert (output / "foreign.txt").read_text(encoding="utf-8") == "foreign"
    assert (
        load_trusted_description_cache(displaced_new)
        .cache.lookup("物品", "ratf", "扩展提示", None)[0]
        .raw_value
        == "second"
    )
    assert any(
        row.role.value == "recovery" and row.identity == previous_identity
        for row in raised.value.retained
    )
    _assert_live(raised.value.retained)


@pytest.mark.parametrize("factory", (_regular_file, _dangling_symlink))
def test_source_swap_records_non_directory_recovery_without_following(
    tmp_path: Path,
    factory: ObjectFactory,
) -> None:
    source = tmp_path / ".w3xray-description-cache-stage-object"
    source.mkdir()
    expected = _identity(source)
    displaced = tmp_path / "displaced-directory"
    foreign = tmp_path / "foreign-object"
    link_text = factory(foreign)
    foreign_identity = _identity(foreign)
    names = RetainedCacheNames(tmp_path, "3" * 32)
    swapped = False

    def swap_then_rename(descriptor: int, source_name: str, target_name: str) -> None:
        nonlocal swapped
        if not swapped:
            swapped = True
            os.rename(
                source_name,
                displaced.name,
                src_dir_fd=descriptor,
                dst_dir_fd=descriptor,
            )
            os.rename(
                foreign.name, source_name, src_dir_fd=descriptor, dst_dir_fd=descriptor
            )
        rename_in_parent(descriptor, source_name, target_name)

    descriptor = os.open(tmp_path, _DIRECTORY_FLAGS)
    try:
        with pytest.raises(PublicationCommitContextError) as raised:
            retention.retain_object(
                descriptor,
                _identity(tmp_path),
                source,
                expected,
                names,
                RetainedCacheRole.FAILED_STAGE,
                swap_then_rename,
            )
    finally:
        os.close(descriptor)

    recovery = names.path(RetainedCacheRole.RECOVERY)
    assert _identity(recovery) == foreign_identity
    assert raised.value.retained[0].identity == foreign_identity
    assert _identity(displaced) == expected
    if link_text is not None:
        assert os.readlink(recovery) == link_text
