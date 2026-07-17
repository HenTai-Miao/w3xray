"""Rollback-source selection refreshes prior transient evidence."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.description_cache_publication_fixture import (
    assert_live_retained_records,
    open_parent,
)
from w3xtool.description_cache_publication_errors import (
    PublicationCommitContextError,
)
from w3xtool.description_cache_publication_models import PublicationTransientRecord
from w3xtool.description_cache_publication_rollback_selection import (
    select_live_identity_path,
)


def _identity(path: Path) -> tuple[int, int]:
    details = path.stat(follow_symlinks=False)
    return details.st_dev, details.st_ino


def test_rollback_selection_failure_reproves_seeded_transient_evidence(
    tmp_path: Path,
) -> None:
    # Given: prior transient evidence names an inode that has since been replaced.
    transient_path = tmp_path / "backup"
    displaced = tmp_path / "displaced"
    transient_path.mkdir()
    stale_identity = _identity(transient_path)
    transient_path.rename(displaced)
    transient_path.mkdir()
    current_identity = _identity(transient_path)
    parent_identity = _identity(tmp_path)
    seeded = PublicationTransientRecord(
        tmp_path,
        transient_path.name,
        parent_identity,
        stale_identity,
    )

    # When: rollback selection has no candidate and rebuilds its error evidence.
    with open_parent(tmp_path) as descriptor:
        with pytest.raises(PublicationCommitContextError) as raised:
            _ = select_live_identity_path(
                descriptor,
                tmp_path,
                parent_identity,
                (),
                (7, 8),
                (),
                (seeded,),
            )

    # Then: only the current name/inode escapes, never the stale pair.
    assert _identity(displaced) == stale_identity
    assert raised.value.retained == ()
    assert raised.value.transient == (
        PublicationTransientRecord(
            tmp_path,
            transient_path.name,
            parent_identity,
            current_identity,
        ),
    )
    assert raised.value.failures == ()
    assert_live_retained_records(raised.value.retained)


__all__: tuple[str, ...] = ()
