"""End-to-end retained-generation publication outcomes."""

from __future__ import annotations

from collections.abc import Sequence
import importlib
from pathlib import Path
import shutil
import sys
from typing import Never

import pytest

from tests.description_cache_publication_fixture import replacement_inputs
from tests.trusted_description_cache_fixture import published_cache
from w3xtool import description_cache_publication as publication
from w3xtool import description_cache_publication_stage as publication_stage
from w3xtool.atomic_rename import AtomicRenameUnavailableError
from w3xtool.description_cache_migration import (
    DescriptionCacheMigrationOptions,
    migrate_description_cache,
)
from w3xtool.description_cache_migration_models import (
    DescriptionCacheRejection,
    ProvenDescriptionCandidate,
)
from w3xtool.description_cache_publication import DescriptionCachePublicationError
from w3xtool.trusted_description_cache import (
    VerifiedDescriptionCache,
    load_trusted_description_cache,
)
from w3xtool.trusted_description_cache_models import TrustedCacheLeafProof


def _identity(path: Path) -> tuple[int, int]:
    details = path.stat(follow_symlinks=False)
    return details.st_dev, details.st_ino


def _transient_paths(output: Path) -> tuple[Path, ...]:
    return tuple(
        path
        for pattern in (
            ".w3xray-description-cache-stage-*",
            ".w3xray-description-cache-backup-*",
        )
        for path in output.parent.glob(pattern)
    )


def _retained_paths(output: Path) -> tuple[Path, ...]:
    return tuple(output.parent.glob(".w3xray-description-cache-retained-*-*"))


def _instrument_preflight_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, int]:
    calls: dict[str, int] = dict.fromkeys(
        ("uuid4", "mkdir", "writer", "rename_noreplace", "rename_exchange"),
        0,
    )

    def forbidden_uuid4() -> Never:
        calls["uuid4"] += 1
        raise AssertionError("UUID allocation ran before support preflight")

    def forbidden_mkdir(
        _name: str,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> Never:
        del mode, dir_fd
        calls["mkdir"] += 1
        raise AssertionError("stage mkdir ran before support preflight")

    def forbidden_writer(
        _source_root: Path,
        _stage_descriptor: int,
        _display_root: Path,
        _accepted: Sequence[ProvenDescriptionCandidate],
        _rejections: Sequence[DescriptionCacheRejection],
    ) -> tuple[TrustedCacheLeafProof, ...]:
        calls["writer"] += 1
        raise AssertionError("stage writer ran before support preflight")

    def forbidden_noreplace(
        _parent_descriptor: int,
        _source_name: str,
        _destination_name: str,
    ) -> Never:
        calls["rename_noreplace"] += 1
        raise AssertionError("no-replace ran before support preflight")

    def forbidden_exchange(
        _parent_descriptor: int,
        _source_name: str,
        _destination_name: str,
    ) -> Never:
        calls["rename_exchange"] += 1
        raise AssertionError("exchange ran before support preflight")

    monkeypatch.setattr(publication, "uuid4", forbidden_uuid4)
    monkeypatch.setattr(publication_stage.os, "mkdir", forbidden_mkdir)
    monkeypatch.setattr(
        publication,
        "build_description_cache_stage",
        forbidden_writer,
        raising=False,
    )
    monkeypatch.setattr(publication, "_rename_noreplace", forbidden_noreplace)
    monkeypatch.setattr(publication, "_rename_exchange", forbidden_exchange)
    return calls


def test_replacement_retains_exact_previous_inode_without_rmtree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = published_cache(tmp_path / "first", raw="first")
    previous_identity = _identity(root)
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "second")

    monkeypatch.delattr(shutil, "rmtree")
    result = migrate_description_cache(
        DescriptionCacheMigrationOptions(legacy_output, legacy_cache, root)
    )

    assert len(result.retained) == 1
    retained = result.retained[0]
    assert retained.role.value == "previous"
    assert retained.identity == previous_identity == _identity(retained.path)
    assert (
        load_trusted_description_cache(retained.path)
        .cache.lookup("物品", "ratf", "扩展提示", None)[0]
        .raw_value
        == "first"
    )
    assert not _transient_paths(root)


def test_first_publication_validation_failure_retains_failed_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "first")
    output = tmp_path / "trusted"
    original = getattr(publication, "_require_valid_at")
    installed_identity: list[tuple[int, int]] = []

    def reject_installed_output(
        parent_descriptor: int,
        path: Path,
    ) -> VerifiedDescriptionCache:
        if path == output:
            installed_identity.append(_identity(path))
            raise OSError("post-publication proof failed")
        return original(parent_descriptor, path)

    monkeypatch.setattr(publication, "_require_valid_at", reject_installed_output)
    with pytest.raises(DescriptionCachePublicationError) as raised:
        migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, output)
        )

    assert not output.exists()
    assert len(installed_identity) == len(raised.value.retained) == 1
    record = raised.value.retained[0]
    assert record.role.value == "failed-output"
    assert record.identity == installed_identity[0] == _identity(record.path)
    assert not _transient_paths(output)


def test_retained_siblings_are_never_implicitly_loaded(tmp_path: Path) -> None:
    output = published_cache(tmp_path / "first", raw="first")
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "second")

    result = migrate_description_cache(
        DescriptionCacheMigrationOptions(legacy_output, legacy_cache, output)
    )

    assert len(result.retained) == 1
    assert (
        load_trusted_description_cache(output)
        .cache.lookup("物品", "ratf", "扩展提示", None)[0]
        .raw_value
        == "second"
    )


def test_atomic_rename_unsupported_fails_before_any_publication_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "first")
    output = tmp_path / "trusted"
    calls = _instrument_preflight_effects(monkeypatch)
    monkeypatch.setattr(sys, "platform", "unsupported")

    with pytest.raises(AtomicRenameUnavailableError):
        migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, output)
        )

    assert calls == dict.fromkeys(calls, 0)
    assert (
        not output.exists()
        and not _transient_paths(output)
        and not _retained_paths(output)
    )


def test_stage_io_unsupported_fails_before_any_publication_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "first")
    output = tmp_path / "trusted"
    stage_io = importlib.import_module("w3xtool.description_cache_publication_stage_io")
    calls = _instrument_preflight_effects(monkeypatch)
    monkeypatch.setattr(stage_io, "_STAGE_IO_AVAILABLE", False)

    with pytest.raises(
        DescriptionCachePublicationError, match="stage I/O is unavailable"
    ):
        migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, output)
        )

    assert calls == dict.fromkeys(calls, 0)
    assert (
        not output.exists()
        and not _transient_paths(output)
        and not _retained_paths(output)
    )
