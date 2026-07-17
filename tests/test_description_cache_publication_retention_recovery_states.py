"""Complete two-name recovery-move postconditions."""

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
)
from w3xtool.description_cache_publication_models import RetainedCacheRole
from w3xtool.description_cache_publication_retention import retain_object
from w3xtool.description_cache_publication_retention_names import RetainedCacheNames
from w3xtool.description_cache_publication_retention_recovery import (
    move_object_to_recovery,
)


def _identity(path: Path) -> tuple[int, int]:
    details = path.stat(follow_symlinks=False)
    return details.st_dev, details.st_ino


def test_recovery_move_completion_then_callable_fault_keeps_exact_record(
    tmp_path: Path,
) -> None:
    # Given: recovery rename completes before its callable raises.
    source = tmp_path / "source"
    source.mkdir()
    expected = _identity(source)
    names = RetainedCacheNames(tmp_path, "1" * 32)
    move_fault = RuntimeError("recovery returned by exception")

    def move_then_raise(
        descriptor: int,
        source_name: str,
        target_name: str,
    ) -> None:
        rename_in_parent(descriptor, source_name, target_name)
        raise move_fault

    # When: both source and recovery names are re-proved after the exception.
    with open_parent(tmp_path) as descriptor:
        with pytest.raises(PublicationCommitContextError) as raised:
            _ = move_object_to_recovery(
                descriptor,
                _identity(tmp_path),
                source,
                expected,
                names,
                move_then_raise,
            )

    # Then: the exact recovery inode and initiating fault are both authoritative.
    recovery = names.path(RetainedCacheRole.RECOVERY)
    assert raised.value.retained[0].identity == expected
    assert _identity(recovery) == expected
    assert raised.value.transient == ()
    assert_failure_order(raised.value, (move_fault,))
    assert raised.value.__cause__ is move_fault
    assert_live_retained_records(raised.value.retained)


def test_recovery_move_return_then_source_reacquisition_surfaces_both_sides(
    tmp_path: Path,
) -> None:
    # Given: recovery succeeds but a foreign object immediately reacquires source.
    source = tmp_path / "source"
    source.mkdir()
    expected = _identity(source)
    names = RetainedCacheNames(tmp_path, "2" * 32)
    reacquired: list[tuple[int, int]] = []

    def move_then_reacquire(
        descriptor: int,
        source_name: str,
        target_name: str,
    ) -> None:
        rename_in_parent(descriptor, source_name, target_name)
        os.mkdir(source_name, dir_fd=descriptor)
        reacquired.append(_identity(source))

    # When: the mandatory postcondition reads both names.
    with open_parent(tmp_path) as descriptor:
        with pytest.raises(PublicationCommitContextError) as raised:
            _ = move_object_to_recovery(
                descriptor,
                _identity(tmp_path),
                source,
                expected,
                names,
                move_then_reacquire,
            )

    # Then: recovery stays retained and current source is separately transient.
    assert len(reacquired) == 1
    assert raised.value.retained[0].identity == expected
    assert tuple((item.path, item.identity) for item in raised.value.transient) == (
        (source, reacquired[0]),
    )
    assert raised.value.failures == ()
    assert_live_retained_records(raised.value.retained)


def test_exact_candidate_already_at_recovery_returns_record_without_rename(
    tmp_path: Path,
) -> None:
    # Given: the candidate already occupies its transaction recovery leaf.
    names = RetainedCacheNames(tmp_path, "3" * 32)
    recovery = names.path(RetainedCacheRole.RECOVERY)
    recovery.mkdir()
    expected = _identity(recovery)
    rename_calls: list[tuple[str, str]] = []

    def reject_rename(_descriptor: int, source: str, target: str) -> None:
        rename_calls.append((source, target))
        raise AssertionError("source-equals-target must not rename")

    # When: recovery proof receives the already-normalized candidate.
    with open_parent(tmp_path) as descriptor:
        record = move_object_to_recovery(
            descriptor,
            _identity(tmp_path),
            recovery,
            expected,
            names,
            reject_rename,
        )

    # Then: it records the exact live object without invoking rename.
    assert rename_calls == []
    assert record.path == recovery
    assert record.role is RetainedCacheRole.RECOVERY
    assert record.identity == expected
    assert_live_retained_records((record,))


def test_already_recovery_candidate_that_disappeared_has_no_phantom_transient(
    tmp_path: Path,
) -> None:
    # Given: the expected candidate left recovery before proof began.
    names = RetainedCacheNames(tmp_path, "4" * 32)
    recovery = names.path(RetainedCacheRole.RECOVERY)
    recovery.mkdir()
    expected = _identity(recovery)
    displaced = tmp_path / "displaced"
    _ = recovery.rename(displaced)

    # When: source-equals-recovery proof sees readable absence.
    with open_parent(tmp_path) as descriptor:
        with pytest.raises(PublicationCommitContextError) as raised:
            _ = move_object_to_recovery(
                descriptor,
                _identity(tmp_path),
                recovery,
                expected,
                names,
                rename_in_parent,
            )

    # Then: absence creates neither a retained nor a phantom transient record.
    assert raised.value.retained == ()
    assert raised.value.transient == ()
    assert raised.value.failures == ()
    assert _identity(displaced) == expected


def test_normal_target_takeover_preserves_simultaneous_source_side(
    tmp_path: Path,
) -> None:
    # Given: intended move returns after both target and source are taken over.
    source = tmp_path / "source"
    source.mkdir()
    expected = _identity(source)
    displaced = tmp_path / "displaced-expected"
    names = RetainedCacheNames(tmp_path, "5" * 32)
    target_foreign: list[tuple[int, int]] = []
    source_foreign: list[tuple[int, int]] = []
    takeover_complete = False

    def takeover_both_names(
        descriptor: int,
        source_name: str,
        target_name: str,
    ) -> None:
        nonlocal takeover_complete
        if takeover_complete:
            rename_in_parent(descriptor, source_name, target_name)
            return
        rename_in_parent(descriptor, source_name, target_name)
        os.rename(
            target_name,
            displaced.name,
            src_dir_fd=descriptor,
            dst_dir_fd=descriptor,
        )
        os.mkdir(target_name, dir_fd=descriptor)
        target_foreign.append(_identity(tmp_path / target_name))
        os.mkdir(source_name, dir_fd=descriptor)
        source_foreign.append(_identity(source))
        takeover_complete = True

    # When: intended-role proof normalizes the unexpected target to recovery.
    with open_parent(tmp_path) as descriptor:
        with pytest.raises(PublicationCommitContextError) as raised:
            _ = retain_object(
                descriptor,
                _identity(tmp_path),
                source,
                expected,
                names,
                RetainedCacheRole.PREVIOUS,
                takeover_both_names,
            )

    # Then: expected, target takeover, and simultaneous source takeover all survive.
    assert len(target_foreign) == len(source_foreign) == 1
    assert _identity(displaced) == expected
    assert raised.value.retained[0].identity == target_foreign[0]
    assert _identity(names.path(RetainedCacheRole.RECOVERY)) == target_foreign[0]
    assert tuple((item.path, item.identity) for item in raised.value.transient) == (
        (source, source_foreign[0]),
    )
    assert_live_retained_records(raised.value.retained)


__all__: tuple[str, ...] = ()
