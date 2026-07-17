"""Ordinary exception matrix for independent private-artifact attempts."""

from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path
from typing import Literal, Never, assert_never

import pytest

from tests.description_cache_publication_fixture import (
    assert_live_retained_records,
    bound_stage,
    rename_in_parent,
)
from w3xtool import description_cache_publication_stage_finalization as finalization
from w3xtool.description_cache_publication_errors import PublicationCommitContextError
from w3xtool.description_cache_publication_models import (
    PublicationTransientRecord,
    RetainedCacheRecord,
    RetainedCacheRole,
)
from w3xtool.description_cache_publication_private_attempt import PrivateAttempt
from w3xtool.description_cache_publication_retention_names import RetainedCacheNames
from w3xtool.description_cache_publication_stage import BoundDescriptionCacheStage


type FaultType = type[ValueError] | type[RuntimeError]
type PrivateSite = Literal["backup", "stage"]
type Rename = Callable[[int, str, str], None]
type Sync = Callable[[int], None]


def _identity(path: Path) -> tuple[int, int]:
    details = path.stat(follow_symlinks=False)
    return details.st_dev, details.st_ino


@pytest.mark.parametrize("fault_type", (ValueError, RuntimeError))
@pytest.mark.parametrize("site", ("backup", "stage"))
def test_private_ordinary_fault_keeps_failed_leaf_and_attempts_other_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault_type: FaultType,
    site: PrivateSite,
) -> None:
    # Given: both private leaves exist and one selected operation raises ordinarily.
    stage = tmp_path / "stage"
    backup = tmp_path / "backup"
    output = tmp_path / "trusted"
    stage.mkdir()
    backup.mkdir()
    stage_identity = _identity(stage)
    backup_identity = _identity(backup)
    names = RetainedCacheNames(tmp_path, "1" * 32)
    fault = fault_type(f"ordinary {site} finalization")
    attempts: list[str] = []
    original_attempt = finalization.attempt_private

    def observe_attempt(
        bound: BoundDescriptionCacheStage,
        path: Path,
        held_identity: tuple[int, int] | None,
        operation: Callable[[], RetainedCacheRecord | None],
    ) -> PrivateAttempt:
        attempts.append("backup" if held_identity is None else "stage")
        return original_attempt(bound, path, held_identity, operation)

    monkeypatch.setattr(finalization, "attempt_private", observe_attempt)
    match site:
        case "backup":

            def fail_backup(
                _bound: BoundDescriptionCacheStage,
                _backup: Path,
                _names: RetainedCacheNames,
                _rename: Rename,
                _sync: Sync,
            ) -> Never:
                raise fault

            monkeypatch.setattr(finalization, "retain_backup", fail_backup)
        case "stage":

            def fail_stage(
                _bound: BoundDescriptionCacheStage,
                _output: Path,
                _names: RetainedCacheNames,
                _rename: Rename,
                _sync: Sync,
                _known_retained: tuple[RetainedCacheRecord, ...],
                _known_transient: tuple[PublicationTransientRecord, ...],
            ) -> Never:
                raise fault

            monkeypatch.setattr(finalization, "retain_stage", fail_stage)
        case unreachable:
            assert_never(unreachable)

    # When: aggregate finalization isolates the first attempt from the second.
    with bound_stage(stage) as bound:
        with pytest.raises(PublicationCommitContextError) as raised:
            _ = finalization.finalize_private_artifacts(
                bound,
                backup,
                output,
                names,
                rename_in_parent,
                os.fsync,
            )

    # Then: both names were attempted and the exact ordinary object is reachable once.
    assert attempts == ["backup", "stage"]
    assert sum(current is fault for current in raised.value.failures) == 1
    assert raised.value.__cause__ is not raised.value
    assert_live_retained_records(raised.value.retained)
    match site:
        case "backup":
            assert any(
                record.role is RetainedCacheRole.FAILED_STAGE
                for record in raised.value.retained
            )
            assert any(
                item.leaf_name == backup.name and item.identity == backup_identity
                for item in raised.value.transient
            )
        case "stage":
            assert any(
                record.role is RetainedCacheRole.RECOVERY
                for record in raised.value.retained
            )
            assert any(
                item.leaf_name == stage.name and item.held_identity == stage_identity
                for item in raised.value.transient
            )
        case unreachable:
            assert_never(unreachable)


__all__: tuple[str, ...] = ()
