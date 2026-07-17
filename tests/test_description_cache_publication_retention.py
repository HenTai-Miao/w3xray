"""Atomic non-destructive retention of trusted-cache generations."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.description_cache_publication_fixture import rename_in_parent
from w3xtool import description_cache_publication_retention as retention
from w3xtool.description_cache_publication_errors import (
    PublicationCommitContextError,
)
from w3xtool.description_cache_publication_models import RetainedCacheRole
from w3xtool.description_cache_publication_models import RetainedCacheRecord
from w3xtool.description_cache_publication_retention_names import RetainedCacheNames
from w3xtool import description_cache_publication_errors as errors


def _identity(path: Path) -> tuple[int, int]:
    details = path.stat(follow_symlinks=False)
    return details.st_dev, details.st_ino


def _open_parent(path: Path) -> int:
    return os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )


def test_retain_object_moves_the_exact_inode_without_overwrite(
    tmp_path: Path,
) -> None:
    source = tmp_path / ".w3xray-description-cache-backup-a"
    source.mkdir()
    expected = _identity(source)
    names = RetainedCacheNames(tmp_path, "1" * 32)
    descriptor = _open_parent(tmp_path)
    try:
        retained = retention.retain_object(
            descriptor,
            _identity(tmp_path),
            source,
            expected,
            names,
            RetainedCacheRole.PREVIOUS,
            rename_in_parent,
        )
    finally:
        os.close(descriptor)

    assert retained.role is RetainedCacheRole.PREVIOUS
    assert retained.identity == expected
    assert retained.path == names.path(RetainedCacheRole.PREVIOUS)
    assert _identity(retained.path) == expected
    assert not source.exists()


def test_source_swap_immediately_before_retention_preserves_both_directories(
    tmp_path: Path,
) -> None:
    source = tmp_path / ".w3xray-description-cache-backup-b"
    source.mkdir()
    expected = _identity(source)
    displaced = tmp_path / "displaced-expected"
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    foreign_identity = _identity(foreign)
    names = RetainedCacheNames(tmp_path, "2" * 32)
    swapped = False

    def swap_then_rename(
        parent_descriptor: int,
        source_name: str,
        destination_name: str,
    ) -> None:
        nonlocal swapped
        if not swapped:
            swapped = True
            os.rename(
                source_name,
                displaced.name,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
            )
            os.rename(
                foreign.name,
                source_name,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
            )
        rename_in_parent(parent_descriptor, source_name, destination_name)

    descriptor = _open_parent(tmp_path)
    try:
        with pytest.raises(
            PublicationCommitContextError, match="NEEDS_CONTEXT"
        ) as raised:
            retention.retain_object(
                descriptor,
                _identity(tmp_path),
                source,
                expected,
                names,
                RetainedCacheRole.PREVIOUS,
                swap_then_rename,
            )
    finally:
        os.close(descriptor)

    assert _identity(displaced) == expected
    recovery = names.path(RetainedCacheRole.RECOVERY)
    assert _identity(recovery) == foreign_identity
    assert raised.value.retained[0].identity == foreign_identity


def test_retain_object_never_overwrites_an_existing_retained_name(
    tmp_path: Path,
) -> None:
    source = tmp_path / ".w3xray-description-cache-stage-c"
    source.mkdir()
    expected = _identity(source)
    names = RetainedCacheNames(tmp_path, "4" * 32)
    collision = names.path(RetainedCacheRole.FAILED_STAGE)
    collision.mkdir()
    collision_identity = _identity(collision)
    descriptor = _open_parent(tmp_path)
    try:
        with pytest.raises(
            PublicationCommitContextError, match="NEEDS_CONTEXT"
        ) as raised:
            retention.retain_object(
                descriptor,
                _identity(tmp_path),
                source,
                expected,
                names,
                RetainedCacheRole.FAILED_STAGE,
                rename_in_parent,
            )
    finally:
        os.close(descriptor)

    recovery = names.path(RetainedCacheRole.RECOVERY)
    assert _identity(collision) == collision_identity
    assert _identity(recovery) == expected
    assert raised.value.retained[0].path == recovery


def test_unmoved_exact_source_does_not_create_an_absent_target_transient(
    tmp_path: Path,
) -> None:
    source = tmp_path / ".w3xray-description-cache-stage-d"
    source.mkdir()
    expected = _identity(source)
    names = RetainedCacheNames(tmp_path, "5" * 32)
    descriptor = _open_parent(tmp_path)

    def leave_unmoved(
        _parent_descriptor: int,
        _source_name: str,
        _destination_name: str,
    ) -> None:
        return

    try:
        with pytest.raises(PublicationCommitContextError) as raised:
            retention.retain_object(
                descriptor,
                _identity(tmp_path),
                source,
                expected,
                names,
                RetainedCacheRole.FAILED_STAGE,
                leave_unmoved,
            )
    finally:
        os.close(descriptor)

    assert tuple((row.path, row.identity) for row in raised.value.transient) == (
        (source, expected),
    )
    assert not names.path(RetainedCacheRole.FAILED_STAGE).exists()


@pytest.mark.parametrize(
    ("earlier_indices", "later_indices", "expected_indices"),
    (((0,), (1, 2), (0, 1, 2)), ((0, 1), (1, 2), (0, 1, 2)), ((0,), (0,), (0,))),
)
def test_merge_retained_preserves_first_occurrence_order(
    tmp_path: Path,
    earlier_indices: tuple[int, ...],
    later_indices: tuple[int, ...],
    expected_indices: tuple[int, ...],
) -> None:
    rows = tuple(
        RetainedCacheRecord(tmp_path / str(index), RetainedCacheRole.PREVIOUS, 1, index)
        for index in range(3)
    )
    earlier = tuple(rows[index] for index in earlier_indices)
    later = tuple(rows[index] for index in later_indices)

    assert errors.merge_retained(earlier, later) == tuple(
        rows[index] for index in expected_indices
    )


@pytest.mark.parametrize(
    ("earlier_indices", "later_indices", "expected_indices"),
    (((0,), (1, 2), (0, 1, 2)), ((0, 1), (1, 2), (0, 1, 2)), ((0,), (0,), (0,))),
)
def test_merge_failures_deduplicates_only_by_identity(
    earlier_indices: tuple[int, ...],
    later_indices: tuple[int, ...],
    expected_indices: tuple[int, ...],
) -> None:
    failures = (OSError("equal"), OSError("equal"), RuntimeError("later"))
    actual = errors.merge_failures(
        tuple(failures[index] for index in earlier_indices),
        tuple(failures[index] for index in later_indices),
    )

    assert len(actual) == len(expected_indices)
    assert all(
        actual[index] is failures[value] for index, value in enumerate(expected_indices)
    )
