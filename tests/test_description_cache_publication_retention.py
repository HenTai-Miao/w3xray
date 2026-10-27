"""Atomic non-destructive retention of trusted-cache generations."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from gametool.description_cache_publication_models import RetainedCacheRole
from gametool.description_cache_publication_models import RetainedCacheRecord
from gametool import description_cache_publication_errors as errors


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
