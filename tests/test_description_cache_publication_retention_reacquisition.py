"""Installed retained-target source-name reacquisition."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.description_cache_publication_fixture import (
    assert_failure_order,
    assert_live_retained_records,
    open_parent,
    rename_in_parent,
)
from w3xtool.description_cache_publication_errors import (
    PublicationCommitContextError,
    RetainedObjectInstalledContextError,
)
from w3xtool.description_cache_publication_models import RetainedCacheRole
from w3xtool.description_cache_publication_retention import retain_object
from w3xtool.description_cache_publication_retention_names import RetainedCacheNames


def _identity(path: Path) -> tuple[int, int]:
    details = path.stat(follow_symlinks=False)
    return details.st_dev, details.st_ino


def test_installed_target_reacquisition_keeps_move_fault_after_recovery_success(
    tmp_path: Path,
) -> None:
    # Given: the intended move completes, source is reacquired, then callable faults.
    source = tmp_path / "source"
    source.mkdir()
    expected = _identity(source)
    names = RetainedCacheNames(tmp_path, "1" * 32)
    move_fault = RuntimeError("intended move returned by exception")
    reacquired: list[tuple[int, int]] = []

    def move_reacquire_then_raise(
        descriptor: int,
        source_name: str,
        target_name: str,
    ) -> None:
        rename_in_parent(descriptor, source_name, target_name)
        if target_name.endswith("-previous"):
            os.mkdir(source_name, dir_fd=descriptor)
            reacquired.append(_identity(source))
            raise move_fault

    # When: postcondition proof normalizes the reacquired source to recovery.
    with open_parent(tmp_path) as descriptor:
        with pytest.raises(RetainedObjectInstalledContextError) as raised:
            _ = retain_object(
                descriptor,
                _identity(tmp_path),
                source,
                expected,
                names,
                RetainedCacheRole.PREVIOUS,
                move_reacquire_then_raise,
            )

    # Then: installed and recovery objects survive with only the move fault ledgered.
    assert len(reacquired) == 1
    assert_failure_order(raised.value, (move_fault,))
    assert raised.value.__cause__ is move_fault
    assert raised.value.installed.identity == expected
    assert _identity(raised.value.installed.path) == expected
    recovery = names.path(RetainedCacheRole.RECOVERY)
    assert _identity(recovery) == reacquired[0]
    assert_live_retained_records(raised.value.retained)


def test_installed_target_reacquisition_keeps_move_and_recovery_faults(
    tmp_path: Path,
) -> None:
    # Given: intended installation faults after completion and recovery is rejected.
    source = tmp_path / "source"
    source.mkdir()
    expected = _identity(source)
    names = RetainedCacheNames(tmp_path, "2" * 32)
    move_fault = RuntimeError("intended move")
    recovery_fault = FileExistsError("recovery rejected")

    def fail_both_moves(
        descriptor: int,
        source_name: str,
        target_name: str,
    ) -> None:
        if target_name.endswith("-previous"):
            rename_in_parent(descriptor, source_name, target_name)
            os.mkdir(source_name, dir_fd=descriptor)
            raise move_fault
        raise recovery_fault

    # When: installed-target handling cannot normalize the reacquired source.
    with open_parent(tmp_path) as descriptor:
        with pytest.raises(RetainedObjectInstalledContextError) as raised:
            _ = retain_object(
                descriptor,
                _identity(tmp_path),
                source,
                expected,
                names,
                RetainedCacheRole.PREVIOUS,
                fail_both_moves,
            )

    # Then: both exact faults remain ordered and both typed causes stay reachable.
    assert_failure_order(raised.value, (move_fault, recovery_fault))
    recovery_error = raised.value.__cause__
    assert type(recovery_error) is PublicationCommitContextError
    assert recovery_error.__cause__ is recovery_fault
    assert _identity(raised.value.installed.path) == expected
    assert _identity(source) != expected
    assert_live_retained_records(raised.value.retained)


def test_completed_intended_move_file_exists_fault_forbids_rollback(
    tmp_path: Path,
) -> None:
    # Given: the no-replace callable installs the exact target, then raises EEXIST.
    source = tmp_path / "source"
    source.mkdir()
    expected = _identity(source)
    names = RetainedCacheNames(tmp_path, "3" * 32)
    move_fault = FileExistsError("raised after installation")

    def install_then_raise(
        descriptor: int,
        source_name: str,
        target_name: str,
    ) -> None:
        rename_in_parent(descriptor, source_name, target_name)
        raise move_fault

    # When: postcondition proof sees the exact intended target and absent source.
    with open_parent(tmp_path) as descriptor:
        with pytest.raises(RetainedObjectInstalledContextError) as raised:
            _ = retain_object(
                descriptor,
                _identity(tmp_path),
                source,
                expected,
                names,
                RetainedCacheRole.FAILED_STAGE,
                install_then_raise,
            )

    # Then: the installed subtype binds the exact target and exposes no rollback record.
    assert raised.value.installed.role is RetainedCacheRole.FAILED_STAGE
    assert _identity(raised.value.installed.path) == expected
    assert raised.value.retained == (raised.value.installed,)
    assert_failure_order(raised.value, (move_fault,))
    assert raised.value.__cause__ is move_fault
    assert_live_retained_records(raised.value.retained)


__all__: tuple[str, ...] = ()
