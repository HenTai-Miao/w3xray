"""Stable and forced held-stage location states."""

from __future__ import annotations

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
from w3xtool.description_cache_publication_models import (
    PublicationTransientRecord,
    RetainedCacheRecord,
    RetainedCacheRole,
)
from w3xtool.description_cache_publication_retention_names import RetainedCacheNames
from w3xtool.description_cache_publication_stage_location import (
    locate_consumed_stage,
)
from w3xtool.description_cache_publication_stage_retention import retain_stage


def _identity(path: Path) -> tuple[int, int]:
    details = path.stat(follow_symlinks=False)
    return details.st_dev, details.st_ino


def test_clean_locator_accepts_held_output_with_known_previous(
    tmp_path: Path,
) -> None:
    # Given: the held new generation is active beside a known old generation.
    stage = tmp_path / ".w3xray-description-cache-stage-a"
    output = tmp_path / "trusted"
    previous_source = tmp_path / "old"
    stage.mkdir()
    previous_source.mkdir()
    names = RetainedCacheNames(tmp_path, "1" * 32)
    previous = names.path(RetainedCacheRole.PREVIOUS)
    _ = previous_source.rename(previous)
    previous_record = RetainedCacheRecord(
        previous,
        RetainedCacheRole.PREVIOUS,
        *_identity(previous),
    )

    # When: both fixed scans locate the held descriptor at output.
    with bound_stage(stage) as bound:
        _ = stage.rename(output)
        located = locate_consumed_stage(
            bound,
            output,
            names,
            known_retained=(previous_record,),
        )

    # Then: output is the unique held match and previous remains independent.
    assert located is None
    assert _identity(previous) == previous_record.identity
    assert_live_retained_records((previous_record,))


def test_clean_locator_returns_exact_record_when_held_stage_is_at_previous(
    tmp_path: Path,
) -> None:
    # Given: an abnormal transaction leaves the held stage at the previous role.
    stage = tmp_path / ".w3xray-description-cache-stage-b"
    output = tmp_path / "trusted"
    stage.mkdir()
    names = RetainedCacheNames(tmp_path, "2" * 32)
    previous = names.path(RetainedCacheRole.PREVIOUS)

    # When: the complete location proof finds one stable retained match.
    with bound_stage(stage) as bound:
        _ = stage.rename(previous)
        located = locate_consumed_stage(bound, output, names)

    # Then: the returned record binds the role, path, and held inode exactly.
    expected = RetainedCacheRecord(
        previous,
        RetainedCacheRole.PREVIOUS,
        *_identity(previous),
    )
    assert located == expected
    assert_live_retained_records((expected,))


def test_known_held_record_surfaces_private_and_retained_foreign_evidence(
    tmp_path: Path,
) -> None:
    # Given: a held failed-stage record plus a known backup and foreign recovery.
    stage = tmp_path / ".w3xray-description-cache-stage-c"
    backup = tmp_path / ".w3xray-description-cache-backup-c"
    output = tmp_path / "trusted"
    stage.mkdir()
    backup.mkdir()
    names = RetainedCacheNames(tmp_path, "3" * 32)
    failed_stage = names.path(RetainedCacheRole.FAILED_STAGE)
    recovery = names.path(RetainedCacheRole.RECOVERY)
    recovery.mkdir()
    with bound_stage(stage) as bound:
        _ = stage.rename(failed_stage)
        held = RetainedCacheRecord(
            failed_stage,
            RetainedCacheRole.FAILED_STAGE,
            *bound.stage_identity,
        )
        backup_evidence = PublicationTransientRecord(
            tmp_path,
            backup.name,
            bound.parent_identity,
            _identity(backup),
        )

        # When: retain_stage routes the already-retained stage through its locator.
        with pytest.raises(PublicationCommitContextError) as raised:
            _ = retain_stage(
                bound,
                output,
                names,
                rename_in_parent,
                lambda _descriptor: None,
                (held,),
                (backup_evidence,),
            )

    # Then: held, private, and foreign retained-name evidence stay disjoint.
    assert raised.value.retained == (held,)
    transient_by_name = {item.leaf_name: item for item in raised.value.transient}
    assert transient_by_name[backup.name].identity == _identity(backup)
    assert transient_by_name[recovery.name].identity == _identity(recovery)
    assert transient_by_name[recovery.name].held_identity is None
    assert_live_retained_records(raised.value.retained)


def test_forced_locator_error_keeps_known_previous_separate_from_held_output(
    tmp_path: Path,
) -> None:
    # Given: a known old generation and the held generation at output.
    stage = tmp_path / ".w3xray-description-cache-stage-d"
    output = tmp_path / "trusted"
    old = tmp_path / "old"
    stage.mkdir()
    old.mkdir()
    names = RetainedCacheNames(tmp_path, "4" * 32)
    previous = names.path(RetainedCacheRole.PREVIOUS)
    _ = old.rename(previous)
    known = RetainedCacheRecord(
        previous,
        RetainedCacheRole.PREVIOUS,
        *_identity(previous),
    )

    # When: an earlier abnormal action forces the otherwise stable locator to fail.
    with bound_stage(stage) as bound:
        _ = stage.rename(output)
        with pytest.raises(PublicationCommitContextError) as raised:
            _ = locate_consumed_stage(
                bound,
                output,
                names,
                known_retained=(known,),
                detail="forced earlier failure",
            )

    # Then: previous remains retained and output alone carries the held identity.
    assert raised.value.retained == (known,)
    held_output = tuple(
        item for item in raised.value.transient if item.leaf_name == output.name
    )
    assert len(held_output) == 1
    assert held_output[0].identity == _identity(output)
    assert held_output[0].held_identity == _identity(output)
    assert all(item.leaf_name != previous.name for item in raised.value.transient)
    assert_live_retained_records(raised.value.retained)


__all__: tuple[str, ...] = ()
