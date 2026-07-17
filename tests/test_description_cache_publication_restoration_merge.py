"""Stable evidence merging across nested restoration failures."""

from __future__ import annotations

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
from w3xtool.description_cache_publication_models import (
    RetainedCacheRecord,
    RetainedCacheRole,
)
from w3xtool.description_cache_publication_recovery_state import (
    normalize_recovery_failure,
)
from w3xtool.description_cache_publication_retention_names import RetainedCacheNames


def _identity(path: Path) -> tuple[int, int]:
    details = path.stat(follow_symlinks=False)
    return details.st_dev, details.st_ino


def test_nested_restoration_errors_merge_overlapping_records_in_first_seen_order(
    tmp_path: Path,
) -> None:
    # Given: the initiating error has A/B and restoration later reports B/C.
    names = RetainedCacheNames(tmp_path, "1" * 32)
    first_path = names.path(RetainedCacheRole.PREVIOUS)
    overlap_path = names.path(RetainedCacheRole.FAILED_OUTPUT)
    candidate = tmp_path / "rollback-candidate"
    first_path.mkdir()
    overlap_path.mkdir()
    candidate.mkdir()
    first = RetainedCacheRecord(
        first_path,
        RetainedCacheRole.PREVIOUS,
        *_identity(first_path),
    )
    overlap = RetainedCacheRecord(
        overlap_path,
        RetainedCacheRole.FAILED_OUTPUT,
        *_identity(overlap_path),
    )
    original_fault = OSError("original retention")
    original = PublicationCommitContextError(
        "original retention; NEEDS_CONTEXT",
        (first, overlap),
        failures=(original_fault,),
    )
    restoration_fault = OSError("restoration retention")

    # When: C is moved to recovery before the nested retention boundary faults.
    with open_parent(tmp_path) as descriptor:

        def fail_after_recovery(
            path: Path,
            identity: tuple[int, int],
            role: RetainedCacheRole,
        ) -> RetainedCacheRecord:
            target = names.path(role)
            rename_in_parent(descriptor, path.name, target.name)
            added = RetainedCacheRecord(target, role, *identity)
            raise PublicationCommitContextError(
                "nested restoration; NEEDS_CONTEXT",
                (overlap, added),
                failures=(restoration_fault,),
            )

        with pytest.raises(PublicationCommitContextError) as raised:
            _ = normalize_recovery_failure(
                descriptor,
                tmp_path,
                _identity(tmp_path),
                (candidate,),
                (9, 10),
                original.retained,
                (),
                (*original.failures, original),
                names,
                fail_after_recovery,
                lambda _descriptor: None,
            )

    # Then: A/B/C are live once each and both failures keep event order.
    recovery = names.path(RetainedCacheRole.RECOVERY)
    added = RetainedCacheRecord(
        recovery,
        RetainedCacheRole.RECOVERY,
        *_identity(recovery),
    )
    assert raised.value.retained == (first, overlap, added)
    assert_live_retained_records(raised.value.retained)
    assert_failure_order(
        raised.value,
        (original_fault, original, restoration_fault),
    )


__all__: tuple[str, ...] = ()
