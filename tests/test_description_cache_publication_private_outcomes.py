"""Unexpected private objects and independent finalization faults."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from tests.description_cache_publication_fixture import (
    assert_live_retained_records,
    bound_stage,
    replacement_inputs,
    transient_publication_paths,
)
from w3xtool import description_cache_publication as publication
from w3xtool import description_cache_publication_stage_finalization as finalization
from w3xtool.description_cache_migration import (
    DescriptionCacheMigrationOptions,
    migrate_description_cache,
)
from w3xtool.description_cache_publication_errors import (
    PublicationCommitContextError,
)
from w3xtool.description_cache_publication_models import (
    DescriptionCachePublicationProof,
    PublicationTransientRecord,
    RetainedCacheRecord,
    RetainedCacheRole,
)
from w3xtool.description_cache_publication_retention_names import RetainedCacheNames
from w3xtool.description_cache_publication_stage import BoundDescriptionCacheStage
from w3xtool.trusted_description_cache import load_trusted_description_cache
from w3xtool.trusted_description_cache_models import (
    VerifiedDescriptionCacheGeneration,
)


def _identity(path: Path) -> tuple[int, int]:
    details = path.stat(follow_symlinks=False)
    return details.st_dev, details.st_ino


def test_unexpected_backup_on_absent_success_is_retained_and_forbids_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: absent-output publication succeeds before a backup appears unexpectedly.
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "first")
    output = tmp_path / "trusted"
    original = publication._publish_valid_stage
    inserted: list[tuple[int, int]] = []

    def insert_backup_after_publish(
        bound: publication.BoundDescriptionCacheStage,
        active: Path,
        backup: Path,
        names: RetainedCacheNames,
        generation: VerifiedDescriptionCacheGeneration,
    ) -> DescriptionCachePublicationProof:
        proof = original(bound, active, backup, names, generation)
        backup.mkdir()
        inserted.append(_identity(backup))
        return proof

    monkeypatch.setattr(
        publication, "_publish_valid_stage", insert_backup_after_publish
    )

    # When: private finalization observes the unexpected backup on a nominal path.
    with pytest.raises(PublicationCommitContextError) as raised:
        _ = migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, output)
        )

    # Then: success is forbidden and the exact backup survives as recovery evidence.
    assert len(inserted) == 1
    assert load_trusted_description_cache(output).cache.entries
    recovery = tuple(
        record
        for record in raised.value.retained
        if record.role is RetainedCacheRole.RECOVERY
    )
    assert len(recovery) == 1
    assert recovery[0].identity == inserted[0]
    assert_live_retained_records(raised.value.retained)
    assert transient_publication_paths(output) == ()


def test_independent_backup_and_stage_faults_are_both_attempted_and_ordered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: both private operations raise distinct ordinary exceptions.
    stage = tmp_path / "stage"
    backup = tmp_path / "backup"
    output = tmp_path / "trusted"
    stage.mkdir()
    backup.mkdir()
    names = RetainedCacheNames(tmp_path, "2" * 32)
    backup_fault = RuntimeError("backup finalization")
    stage_fault = ValueError("stage finalization")
    attempts: list[str] = []

    def fail_backup(
        _bound: BoundDescriptionCacheStage,
        _backup: Path,
        _names: RetainedCacheNames,
        _rename: Callable[[int, str, str], None],
        _sync: Callable[[int], None],
    ) -> None:
        attempts.append("backup")
        raise backup_fault

    def fail_stage(
        _bound: BoundDescriptionCacheStage,
        _output: Path,
        _names: RetainedCacheNames,
        _rename: Callable[[int, str, str], None],
        _sync: Callable[[int], None],
        _known_retained: tuple[RetainedCacheRecord, ...],
        _known_transient: tuple[PublicationTransientRecord, ...],
    ) -> None:
        attempts.append("stage")
        raise stage_fault

    monkeypatch.setattr(finalization, "retain_backup", fail_backup)
    monkeypatch.setattr(finalization, "retain_stage", fail_stage)

    # When: the orchestrator captures each attempt before aggregating evidence.
    with bound_stage(stage) as bound:
        with pytest.raises(PublicationCommitContextError) as raised:
            _ = finalization.finalize_private_artifacts(
                bound,
                backup,
                output,
                names,
                lambda _descriptor, _source, _target: None,
                lambda _descriptor: None,
            )

    # Then: both injected objects precede their typed attempt errors in order.
    assert attempts == ["backup", "stage"]
    assert len(raised.value.failures) == 4
    assert raised.value.failures[0] is backup_fault
    assert type(raised.value.failures[1]) is PublicationCommitContextError
    assert raised.value.failures[2] is stage_fault
    assert type(raised.value.failures[3]) is PublicationCommitContextError
    by_name = {item.leaf_name: item for item in raised.value.transient}
    assert by_name[backup.name].identity == _identity(backup)
    assert by_name[stage.name].held_identity == _identity(stage)


__all__: tuple[str, ...] = ()
