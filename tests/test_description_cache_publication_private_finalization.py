"""Independent private-leaf finalization evidence."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.description_cache_publication_fixture import (
    assert_live_retained_records,
    bound_stage,
    rename_in_parent,
)
from w3xtool.description_cache_publication_errors import (
    PublicationCommitContextError,
)
from w3xtool.description_cache_publication_models import RetainedCacheRole
from w3xtool.description_cache_publication_private_attempt import attempt_private
from w3xtool.description_cache_publication_retention_names import RetainedCacheNames
from w3xtool.description_cache_publication_stage_finalization import (
    finalize_private_artifacts,
)


def _identity(path: Path) -> tuple[int, int]:
    details = path.stat(follow_symlinks=False)
    return details.st_dev, details.st_ino


def test_typed_private_attempt_error_passes_through_by_identity(
    tmp_path: Path,
) -> None:
    # Given: a private operation already produced authoritative typed evidence.
    stage = tmp_path / ".w3xray-description-cache-stage-a"
    stage.mkdir()
    original = OSError("original")
    typed = PublicationCommitContextError(
        "typed locator failure; NEEDS_CONTEXT",
        failures=(original,),
    )

    def raise_typed_error() -> None:
        raise typed

    # When: the independent-attempt boundary captures the operation failure.
    with bound_stage(stage) as bound:
        attempt = attempt_private(bound, stage, bound.stage_identity, raise_typed_error)

    # Then: it does not wrap, mutate, or replace the locator's typed object.
    assert attempt.record is None
    assert attempt.error is typed
    assert typed.failures == (original,)


def test_backup_recovery_record_stays_disjoint_from_later_stage_transient(
    tmp_path: Path,
) -> None:
    # Given: backup can normalize, while the stage's failed-stage target is occupied.
    stage = tmp_path / ".w3xray-description-cache-stage-b"
    backup = tmp_path / ".w3xray-description-cache-backup-b"
    output = tmp_path / "trusted"
    stage.mkdir()
    backup.mkdir()
    names = RetainedCacheNames(tmp_path, "2" * 32)
    failed_stage = names.path(RetainedCacheRole.FAILED_STAGE)
    failed_stage.mkdir()
    backup_identity = _identity(backup)

    # When: finalization attempts backup first and then the colliding held stage.
    with bound_stage(stage) as bound:
        with pytest.raises(PublicationCommitContextError) as raised:
            _ = finalize_private_artifacts(
                bound,
                backup,
                output,
                names,
                rename_in_parent,
                os.fsync,
            )

    # Then: the normalized backup remains retained, never duplicated as transient.
    recovery = names.path(RetainedCacheRole.RECOVERY)
    recovery_records = tuple(
        record
        for record in raised.value.retained
        if record.path == recovery and record.identity == backup_identity
    )
    assert len(recovery_records) == 1
    assert_live_retained_records(raised.value.retained)
    assert all(
        not (item.leaf_name == recovery.name and item.identity == backup_identity)
        for item in raised.value.transient
    )
    assert any(
        item.leaf_name == stage.name and item.held_identity == bound.stage_identity
        for item in raised.value.transient
    )


__all__: tuple[str, ...] = ()
