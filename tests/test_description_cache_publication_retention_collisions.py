"""Retained-role collision behavior for cache publication."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Never

import pytest

from tests.description_cache_publication_fixture import (
    exchange_in_parent,
    replacement_inputs,
)
from tests.trusted_description_cache_fixture import published_cache
from w3xtool import description_cache_publication as publication
from w3xtool.description_cache_migration import (
    DescriptionCacheMigrationOptions,
    migrate_description_cache,
)
from w3xtool.description_cache_publication_errors import PublicationCommitContextError
from w3xtool.trusted_description_cache import (
    VerifiedDescriptionCache,
    load_trusted_description_cache,
)
from w3xtool.trusted_description_cache_models import TrustedCacheLeafProof


def _identity(path: Path) -> tuple[int, int]:
    details = path.stat(follow_symlinks=False)
    return details.st_dev, details.st_ino


def _retained(output: Path, role: str) -> tuple[Path, ...]:
    return tuple(
        path
        for path in output.parent.glob(".w3xray-description-cache-retained-*-*")
        if path.name.endswith(f"-{role}")
    )


def _private(output: Path) -> tuple[Path, ...]:
    return tuple(
        path
        for pattern in (
            ".w3xray-description-cache-stage-*",
            ".w3xray-description-cache-backup-*",
        )
        for path in output.parent.glob(pattern)
    )


def test_previous_role_collision_restores_active_and_retains_failed_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = published_cache(tmp_path / "first", raw="first")
    original_identity = _identity(root)
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "second")
    original = getattr(publication, "_rename_noreplace")
    collisions: list[tuple[Path, tuple[int, int]]] = []

    def collide(descriptor: int, source_name: str, target_name: str) -> None:
        if target_name.endswith("-previous") and not collisions:
            target = root.parent / target_name
            target.mkdir()
            (target / "foreign.txt").write_text("foreign", encoding="utf-8")
            collisions.append((target, _identity(target)))
        original(descriptor, source_name, target_name)

    monkeypatch.setattr(publication, "_rename_noreplace", collide)
    with pytest.raises(PublicationCommitContextError) as raised:
        migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, root)
        )

    assert _identity(root) == original_identity
    assert (
        load_trusted_description_cache(root)
        .cache.lookup("物品", "ratf", "扩展提示", None)[0]
        .raw_value
        == "first"
    )
    assert len(collisions) == 1 and _identity(collisions[0][0]) == collisions[0][1]
    failed = _retained(root, "failed-stage")
    assert len(failed) == 1
    assert (
        load_trusted_description_cache(failed[0])
        .cache.lookup("物品", "ratf", "扩展提示", None)[0]
        .raw_value
        == "second"
    )
    assert any(row.role.value == "failed-stage" for row in raised.value.retained)
    assert not _private(root)


def test_recovery_role_collision_preserves_transient_without_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = published_cache(tmp_path / "first", raw="first")
    previous_identity = _identity(root)
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "second")
    displaced_new = root.parent / "displaced-new"
    collisions: list[tuple[Path, tuple[int, int]]] = []

    def takeover_with_collision(
        descriptor: int,
        source_name: str,
        target_name: str,
    ) -> None:
        exchange_in_parent(descriptor, source_name, target_name)
        transaction_id = source_name.removeprefix(".w3xray-description-cache-stage-")
        collision = root.parent / (
            f".w3xray-description-cache-retained-{transaction_id}-recovery"
        )
        collision.mkdir()
        (collision / "foreign.txt").write_text("foreign", encoding="utf-8")
        collisions.append((collision, _identity(collision)))
        os.rename(
            target_name,
            displaced_new.name,
            src_dir_fd=descriptor,
            dst_dir_fd=descriptor,
        )
        root.mkdir()
        (root / "foreign.txt").write_text("winner", encoding="utf-8")

    monkeypatch.setattr(publication, "_rename_exchange", takeover_with_collision)
    with pytest.raises(PublicationCommitContextError) as raised:
        migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, root)
        )

    assert (root / "foreign.txt").read_text(encoding="utf-8") == "winner"
    assert len(collisions) == 1 and _identity(collisions[0][0]) == collisions[0][1]
    private = _private(root)
    assert len(private) == 1 and _identity(private[0]) == previous_identity
    assert any(row.identity == previous_identity for row in raised.value.transient)


def test_failed_output_collision_moves_exact_output_to_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "first")
    output = tmp_path / "trusted"
    original_validate = getattr(publication, "_require_valid_at")
    original_rename = getattr(publication, "_rename_noreplace")
    installed: list[tuple[int, int]] = []
    collisions: list[tuple[Path, tuple[int, int]]] = []

    def reject_output(descriptor: int, path: Path) -> VerifiedDescriptionCache:
        if path == output:
            installed.append(_identity(path))
            raise OSError("installed output rejected")
        return original_validate(descriptor, path)

    def collide(descriptor: int, source_name: str, target_name: str) -> None:
        if target_name.endswith("-failed-output") and not collisions:
            target = output.parent / target_name
            target.mkdir()
            collisions.append((target, _identity(target)))
        original_rename(descriptor, source_name, target_name)

    monkeypatch.setattr(publication, "_require_valid_at", reject_output)
    monkeypatch.setattr(publication, "_rename_noreplace", collide)

    with pytest.raises(PublicationCommitContextError) as raised:
        migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, output)
        )

    recovery = _retained(output, "recovery")
    assert len(installed) == len(collisions) == len(recovery) == 1
    assert _identity(collisions[0][0]) == collisions[0][1]
    assert _identity(recovery[0]) == installed[0]
    assert raised.value.retained[0].identity == installed[0]
    assert not _private(output)


def test_failed_stage_collision_moves_exact_stage_to_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = published_cache(tmp_path / "first", raw="first")
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "second")
    original_load = getattr(
        publication, "load_trusted_description_cache_from_descriptor"
    )
    original_rename = getattr(publication, "_rename_noreplace")
    stage_identities: list[tuple[int, int]] = []
    collisions: list[tuple[Path, tuple[int, int]]] = []

    def reject_stage(
        descriptor: int,
        path: Path,
        leaves: tuple[TrustedCacheLeafProof, ...],
    ) -> Never:
        _ = original_load(descriptor, path, leaves)
        stage_identities.append(_identity(path))
        raise OSError("stage rejected")

    def collide(descriptor: int, source_name: str, target_name: str) -> None:
        if target_name.endswith("-failed-stage") and not collisions:
            target = output.parent / target_name
            target.mkdir()
            collisions.append((target, _identity(target)))
        original_rename(descriptor, source_name, target_name)

    monkeypatch.setattr(
        publication,
        "load_trusted_description_cache_from_descriptor",
        reject_stage,
    )
    monkeypatch.setattr(publication, "_rename_noreplace", collide)
    with pytest.raises(PublicationCommitContextError) as raised:
        migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, output)
        )

    recovery = _retained(output, "recovery")
    assert len(stage_identities) == len(collisions) == len(recovery) == 1
    assert _identity(collisions[0][0]) == collisions[0][1]
    assert _identity(recovery[0]) == stage_identities[0]
    assert raised.value.retained[0].identity == stage_identities[0]
    assert not _private(output)
