"""Post-mkdir creation normalization and descriptor cleanup."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, assert_never

import pytest

from tests.description_cache_publication_fixture import (
    assert_failure_order,
    assert_live_retained_records,
    rename_in_parent,
)
from w3xtool import description_cache_publication_stage as publication_stage
from w3xtool.description_cache_publication_descriptor_close import (
    DescriptorCloseLedger,
    close_publication_descriptors,
)
from w3xtool.description_cache_publication_errors import (
    PublicationCommitContextError,
)
from w3xtool.description_cache_publication_models import RetainedCacheRole
from w3xtool.description_cache_publication_retention_names import RetainedCacheNames


type PostMkdirSite = Literal["stage-open", "initial-sync"]


def _identity(path: Path) -> tuple[int, int]:
    details = path.stat(follow_symlinks=False)
    return details.st_dev, details.st_ino


@pytest.mark.parametrize("site", ("stage-open", "initial-sync"))
def test_post_mkdir_file_exists_normalizes_created_inode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    site: PostMkdirSite,
) -> None:
    # Given: mkdir succeeds before a later operation raises FileExistsError.
    stage = tmp_path / "stage"
    fault = FileExistsError(f"post-mkdir {site}")
    created: list[tuple[int, int]] = []
    real_open = publication_stage.os.open
    match site:
        case "stage-open":
            fail_stage_open = True
            fail_initial_sync = False
        case "initial-sync":
            fail_stage_open = False
            fail_initial_sync = True
        case unreachable:
            assert_never(unreachable)

    def open_stage(
        path: str | bytes | Path,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if fail_stage_open and path == stage.name and dir_fd is not None:
            created.append(_identity(stage))
            raise fault
        return real_open(path, flags, mode, dir_fd=dir_fd)

    sync_calls = 0

    def sync_parent(descriptor: int) -> None:
        nonlocal sync_calls
        sync_calls += 1
        if fail_initial_sync and sync_calls == 1:
            created.append(_identity(stage))
            raise fault
        os.fsync(descriptor)

    monkeypatch.setattr(publication_stage.os, "open", open_stage)

    # When: the created-stage boundary handles the post-mkdir exception.
    with pytest.raises(PublicationCommitContextError) as raised:
        _ = publication_stage.create_stage_and_capture(
            stage,
            tmp_path / "output",
            RetainedCacheNames(tmp_path, "1" * 32),
            rename_in_parent,
            sync_parent,
        )

    # Then: the created inode is retained, not misclassified as a mkdir collision.
    assert len(created) == 1
    assert_failure_order(raised.value, (fault,))
    assert len(raised.value.retained) == 1
    record = raised.value.retained[0]
    assert record.role is RetainedCacheRole.FAILED_STAGE
    assert record.identity == created[0]
    assert_live_retained_records(raised.value.retained)
    assert not stage.exists()


def test_creation_cleanup_after_both_descriptors_attempts_each_close_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: stage and parent descriptors exist when initial sync faults.
    stage = tmp_path / "stage"
    initiating = RuntimeError("creation sync")
    close_faults = (OSError("stage close"), OSError("parent close"))
    sync_calls = 0
    close_attempts: list[int] = []
    owned: list[int] = []
    real_close = os.close

    def fail_first_sync(descriptor: int) -> None:
        nonlocal sync_calls
        sync_calls += 1
        if sync_calls == 1:
            raise initiating
        os.fsync(descriptor)

    def boundary(
        descriptors: tuple[tuple[str, int], ...],
        in_flight: BaseException | None,
        ledger: DescriptorCloseLedger,
    ) -> None:
        owned.extend(descriptor for _label, descriptor in descriptors)
        fault_by_descriptor = dict(zip(owned, close_faults, strict=True))

        def fail_close(descriptor: int) -> None:
            close_attempts.append(descriptor)
            raise fault_by_descriptor[descriptor]

        close_publication_descriptors(
            descriptors,
            in_flight,
            ledger,
            fail_close,
        )

    monkeypatch.setattr(publication_stage, "close_publication_descriptors", boundary)

    # When: creation normalizes the stage and then exits its owned cleanup boundary.
    try:
        with pytest.raises(PublicationCommitContextError) as raised:
            _ = publication_stage.create_stage_and_capture(
                stage,
                tmp_path / "output",
                RetainedCacheNames(tmp_path, "2" * 32),
                rename_in_parent,
                fail_first_sync,
            )
    finally:
        for descriptor in owned:
            real_close(descriptor)

    # Then: stage and parent closes are each attempted once after the initiating fault.
    assert len(owned) == 2
    assert len(set(owned)) == 2
    assert close_attempts == owned
    assert_failure_order(raised.value, (initiating, *close_faults))
    assert_live_retained_records(raised.value.retained)


__all__: tuple[str, ...] = ()
