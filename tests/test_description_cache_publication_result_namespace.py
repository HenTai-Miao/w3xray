"""Namespace races during terminal publication-result proof."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Literal, assert_never

import pytest

from tests.description_cache_publication_fixture import (
    assert_live_retained_records,
    replacement_inputs,
)
from tests.trusted_description_cache_fixture import published_cache
from w3xtool import (
    description_cache_publication_generation_evidence as generation_evidence,
)
from w3xtool import description_cache_publication_result_evidence as result_evidence
from w3xtool import description_cache_publication_stage_finalization as finalization
from w3xtool.description_cache_migration import (
    DescriptionCacheMigrationOptions,
    migrate_description_cache,
)
from w3xtool.description_cache_publication_errors import (
    PublicationCommitContextError,
)
from w3xtool.description_cache_publication_models import (
    RetainedCacheRecord,
    RetainedEvidenceReproof,
)
from w3xtool.description_cache_publication_private_attempt import PrivateAttempt
from w3xtool.description_cache_publication_stage import BoundDescriptionCacheStage
from w3xtool.trusted_description_cache import load_trusted_description_cache


type LatePrivateKind = Literal["stage", "backup", "both"]


def _identity(path: Path) -> tuple[int, int]:
    details = path.stat(follow_symlinks=False)
    return details.st_dev, details.st_ino


def test_retained_leaf_replaced_between_boundary_reproofs_is_transient(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: replacement commits active and previous before the terminal set proof.
    output = published_cache(tmp_path / "old", raw="first")
    legacy_output, legacy_cache = replacement_inputs(tmp_path / "new", "second")
    original = result_evidence.require_stable_generation_set
    displaced = tmp_path / "displaced-previous"
    replaced: list[tuple[Path, tuple[int, int], tuple[int, int]]] = []

    def replace_retained_before_set_proof(
        parent_descriptor: int,
        parent: Path,
        parent_identity: tuple[int, int],
        generations: tuple[generation_evidence.ExpectedPublishedGeneration, ...],
        private_paths: tuple[Path, Path],
    ) -> None:
        retained = generations[1]
        old_identity = retained.identity
        retained.path.rename(displaced)
        retained.path.mkdir()
        foreign_identity = _identity(retained.path)
        replaced.append((retained.path, old_identity, foreign_identity))
        original(
            parent_descriptor,
            parent,
            parent_identity,
            generations,
            private_paths,
        )

    monkeypatch.setattr(
        result_evidence,
        "require_stable_generation_set",
        replace_retained_before_set_proof,
    )

    # When: the second boundary proof sees a replacement at the retained name.
    with pytest.raises(PublicationCommitContextError) as raised:
        _ = migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, output)
        )

    # Then: the old inode survives displaced and the current name is transient only.
    assert len(replaced) == 1
    retained_path, old_identity, foreign_identity = replaced[0]
    assert _identity(displaced) == old_identity
    assert _identity(retained_path) == foreign_identity
    assert raised.value.retained == ()
    current = tuple(
        item for item in raised.value.transient if item.leaf_name == retained_path.name
    )
    assert len(current) == 1
    assert current[0].identity == foreign_identity


def test_public_parent_replaced_after_final_leaf_reproof_is_never_mutated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: active and previous generations are below a dedicated public parent.
    parent = tmp_path / "publication"
    parent.mkdir()
    output = published_cache(tmp_path / "old", raw="first").rename(parent / "trusted")
    legacy_output, legacy_cache = replacement_inputs(tmp_path / "new", "second")
    original = generation_evidence._namespace_evidence
    displaced = tmp_path / "held-parent"
    replacements = 0

    def replace_parent_after_leaf_reproof(
        parent_descriptor: int,
        current_parent: Path,
        parent_identity: tuple[int, int],
        generations: tuple[generation_evidence.ExpectedPublishedGeneration, ...],
        private_paths: tuple[Path, Path],
    ) -> RetainedEvidenceReproof:
        nonlocal replacements
        proof = original(
            parent_descriptor,
            current_parent,
            parent_identity,
            generations,
            private_paths,
        )
        replacements += 1
        current_parent.rename(displaced)
        current_parent.mkdir()
        return proof

    monkeypatch.setattr(
        generation_evidence,
        "_namespace_evidence",
        replace_parent_after_leaf_reproof,
    )

    # When: the final parent-binding proof follows the last complete leaf proof.
    with pytest.raises(PublicationCommitContextError) as raised:
        _ = migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, output)
        )

    # Then: held active/previous become transient and replacement parent stays empty.
    assert replacements == 1
    assert raised.value.retained == ()
    assert tuple(parent.iterdir()) == ()
    held_identities = {
        _identity(path)
        for path in displaced.iterdir()
        if path.is_dir()
        and not path.name.startswith(".w3xray-description-cache-stage-")
    }
    transient_identities = {
        item.identity for item in raised.value.transient if item.identity is not None
    }
    assert held_identities <= transient_identities


@pytest.mark.parametrize("kind", ("stage", "backup", "both"))
def test_late_private_insertion_is_attempted_and_forbids_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: LatePrivateKind,
) -> None:
    # Given: terminal whole-set proof begins with no private publication names.
    output = published_cache(tmp_path / "old", raw="first")
    legacy_output, legacy_cache = replacement_inputs(tmp_path / "new", "second")
    original_round = generation_evidence._read_generation_round
    original_attempt = finalization.attempt_private
    rounds = 0
    inserted: dict[str, tuple[int, int]] = {}
    attempts: list[str] = []

    def insert_after_first_round(
        parent_descriptor: int,
        descriptors: tuple[int, ...],
        generations: tuple[generation_evidence.ExpectedPublishedGeneration, ...],
        private_paths: tuple[Path, Path],
    ) -> generation_evidence._GenerationRound:
        nonlocal rounds
        result = original_round(
            parent_descriptor,
            descriptors,
            generations,
            private_paths,
        )
        rounds += 1
        if rounds == 1:
            stage, backup = private_paths
            match kind:
                case "stage":
                    selected = (stage,)
                case "backup":
                    selected = (backup,)
                case "both":
                    selected = (stage, backup)
                case unreachable:
                    assert_never(unreachable)
            for path in selected:
                path.mkdir()
                inserted[path.name] = _identity(path)
        return result

    def record_attempt(
        bound: BoundDescriptionCacheStage,
        path: Path,
        held_identity: tuple[int, int] | None,
        operation: Callable[[], RetainedCacheRecord | None],
    ) -> PrivateAttempt:
        attempts.append(path.name)
        return original_attempt(bound, path, held_identity, operation)

    monkeypatch.setattr(
        generation_evidence,
        "_read_generation_round",
        insert_after_first_round,
    )
    monkeypatch.setattr(finalization, "attempt_private", record_attempt)

    # When: the second full round detects one or both late private names.
    with pytest.raises(PublicationCommitContextError) as raised:
        _ = migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, output)
        )

    # Then: backup and stage are independently attempted and all inserted inodes survive.
    assert rounds == 1
    assert len(attempts) >= 2
    assert attempts[0].startswith(".w3xray-description-cache-backup-")
    assert attempts[1].startswith(".w3xray-description-cache-stage-")
    surfaced = {record.identity for record in raised.value.retained} | {
        item.identity for item in raised.value.transient if item.identity is not None
    }
    assert set(inserted.values()) <= surfaced
    assert_live_retained_records(raised.value.retained)
    assert load_trusted_description_cache(output).cache.entries


__all__: tuple[str, ...] = ()
