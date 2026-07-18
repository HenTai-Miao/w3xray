"""Retained-cache no-follow, unreadable, and deterministic race contracts."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.retained_integrity_fixture import active_cache, backup, retained, stage
from w3xtool import description_cache_retained_file_proof as file_api
from w3xtool import description_cache_retained_integrity as snapshot_api
from w3xtool import description_cache_retained_set_scan as set_api
from w3xtool import description_cache_retained_siblings as sibling_api
from w3xtool.description_cache_publication_models import RetainedCacheRole
from w3xtool.description_cache_retained_binding import BoundActiveCache
from w3xtool.description_cache_retained_file_proof import RetainedFileRead
from w3xtool.description_cache_retained_integrity_models import (
    RetainedDescriptionCacheArtifact,
    SiblingState,
)
from w3xtool.description_cache_retained_tree_snapshot import RetainedScanBounds


def test_active_root_symlink_is_a_command_boundary(tmp_path: Path) -> None:
    inspect = getattr(snapshot_api, "inspect_retained_description_caches")
    active = active_cache(tmp_path)
    alias = tmp_path / "alias"
    alias.symlink_to(active, target_is_directory=True)

    with pytest.raises(ValueError):
        inspect(alias)


def test_top_level_and_nested_symlinks_are_never_followed(tmp_path: Path) -> None:
    inspect = getattr(snapshot_api, "inspect_retained_description_caches")
    active = active_cache(tmp_path)
    top = retained(active, "2", "recovery")
    top.symlink_to(tmp_path / "outside", target_is_directory=True)
    nested = retained(active, "3", "failed-output")
    nested.mkdir()
    (nested / "link").symlink_to(tmp_path / "outside")

    report = inspect(active)

    rows = {item.path: item for item in report.retained}
    assert rows[top].validation.value == "unsafe-object"
    assert rows[nested].validation.value == "unsafe-object"
    assert rows[nested].problem_path == "link"


def test_file_identity_mutation_during_read_is_unstable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inspect = getattr(snapshot_api, "inspect_retained_description_caches")
    active = active_cache(tmp_path)
    artifact = retained(active, "2", "failed-stage")
    artifact.mkdir()
    leaf = artifact / "leaf"
    leaf.write_bytes(b"old")
    original = file_api.read_retained_file
    mutated = False

    def mutate(
        descriptor: int,
        maximum: int,
        capture_payload: bool,
    ) -> RetainedFileRead:
        nonlocal mutated
        payload = original(descriptor, maximum, capture_payload)
        if not mutated:
            mutated = True
            leaf.write_bytes(b"new")
        return payload

    monkeypatch.setattr(file_api, "read_retained_file", mutate)

    report = inspect(active)

    assert report.retained[0].validation.value == "unstable"


def test_later_artifact_mutation_marks_early_artifact_unstable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = active_cache(tmp_path)
    early = retained(active, "2", "failed-stage")
    early.mkdir()
    early_leaf = early / "leaf"
    early_leaf.write_bytes(b"old")
    later = retained(active, "3", "failed-output")
    later.mkdir()
    original = set_api.inspect_retained_artifact
    mutated = False

    def mutate_early(
        bound: BoundActiveCache,
        state: SiblingState,
        transaction_id: str,
        role: RetainedCacheRole,
        bounds: RetainedScanBounds,
    ) -> RetainedDescriptionCacheArtifact:
        nonlocal mutated
        if state.name == later.name and not mutated:
            mutated = True
            early_leaf.write_bytes(b"new")
        return original(bound, state, transaction_id, role, bounds)

    monkeypatch.setattr(set_api, "inspect_retained_artifact", mutate_early)

    report = snapshot_api.inspect_retained_description_caches(active)

    rows = {item.path: item for item in report.retained}
    assert rows[early].validation.value == "unstable"
    assert rows[later].validation.value == "partial-evidence"


def test_unreadable_retained_and_transient_names_preserve_unknown_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inspect = getattr(snapshot_api, "inspect_retained_description_caches")
    active = active_cache(tmp_path)
    exact = retained(active, "2", "recovery")
    exact.mkdir()
    temporary = stage(active, "3")
    temporary.mkdir()
    original = sibling_api.stat_sibling

    def deny(parent_descriptor: int, name: str) -> os.stat_result:
        if name in {exact.name, temporary.name}:
            raise PermissionError(name)
        return original(parent_descriptor, name)

    monkeypatch.setattr(sibling_api, "stat_sibling", deny)

    report = inspect(active)

    assert report.retained[0].kind.value == "unknown"
    assert report.retained[0].device is None
    assert report.retained[0].validation.value == "unreadable"
    assert report.transient[0].reason.value == "unreadable-transient"


@pytest.mark.parametrize(
    "operation",
    ["insert-stage", "insert-malformed", "remove-backup", "replace-retained"],
)
def test_relevant_sibling_mutation_is_a_command_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    inspect = getattr(snapshot_api, "inspect_retained_description_caches")
    active = active_cache(tmp_path)
    artifact = retained(active, "2", "recovery")
    artifact.mkdir()
    old_backup = backup(active, "3")
    old_backup.mkdir()
    original = set_api.capture_relevant_siblings
    calls = 0

    def mutate(
        parent_descriptor: int,
        active_name: str,
    ) -> tuple[SiblingState, ...]:
        nonlocal calls
        calls += 1
        if calls == 2:
            if operation == "insert-stage":
                stage(active, "4").mkdir()
            elif operation == "insert-malformed":
                (active.parent / ".w3xray-description-cache-retained-bad").mkdir()
            elif operation == "remove-backup":
                old_backup.rmdir()
            else:
                artifact.rmdir()
                artifact.mkdir()
        return original(parent_descriptor, active_name)

    monkeypatch.setattr(set_api, "capture_relevant_siblings", mutate)

    with pytest.raises(ValueError):
        inspect(active)
