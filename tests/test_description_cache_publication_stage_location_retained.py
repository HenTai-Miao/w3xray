"""Location proof for an already-retained held publication stage."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

import pytest

from tests.description_cache_publication_fixture import (
    assert_live_retained_records,
    rename_in_parent,
)
from w3xtool.description_cache_publication_descriptor_close import (
    DescriptorCloseLedger,
)
from w3xtool.description_cache_publication_errors import (
    PublicationCommitContextError,
)
from w3xtool.description_cache_publication_models import (
    RetainedCacheRecord,
    RetainedCacheRole,
)
from w3xtool.description_cache_publication_retention_names import RetainedCacheNames
from w3xtool.description_cache_publication_stage import BoundDescriptionCacheStage
from w3xtool import description_cache_publication_stage_location as stage_location
from w3xtool import description_cache_publication_stage_location_scan as location_scan
from w3xtool.description_cache_publication_stage_retention import retain_stage


_DIRECTORY_FLAGS: Final = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)


def _identity(path: Path) -> tuple[int, int]:
    details = path.stat(follow_symlinks=False)
    return details.st_dev, details.st_ino


def test_known_retained_stage_still_scans_concurrent_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the exact held stage already has a durable failed-stage record.
    stage = tmp_path / ".w3xray-description-cache-stage-a"
    output = tmp_path / "trusted"
    stage.mkdir()
    parent_descriptor = os.open(tmp_path, _DIRECTORY_FLAGS)
    stage_descriptor = os.open(stage, _DIRECTORY_FLAGS)
    stage_identity = _identity(stage)
    names = RetainedCacheNames(tmp_path, "1" * 32)
    retained_path = names.path(RetainedCacheRole.FAILED_STAGE)
    stage.rename(retained_path)
    record = RetainedCacheRecord(
        retained_path,
        RetainedCacheRole.FAILED_STAGE,
        *stage_identity,
    )
    bound = BoundDescriptionCacheStage(
        parent_descriptor,
        stage_descriptor,
        stage,
        _identity(tmp_path),
        stage_identity,
        DescriptorCloseLedger(),
    )
    original_snapshot = stage_location._snapshot_locations
    snapshot_calls = 0

    def insert_output_after_first_scan(
        current: BoundDescriptionCacheStage,
        active: Path,
        retained_names: RetainedCacheNames,
    ) -> tuple[location_scan._StageLocationState, ...]:
        nonlocal snapshot_calls
        snapshot = original_snapshot(current, active, retained_names)
        snapshot_calls += 1
        if snapshot_calls == 1:
            output.mkdir()
        return snapshot

    monkeypatch.setattr(
        stage_location,
        "_snapshot_locations",
        insert_output_after_first_scan,
    )

    # When: finalization proves the held stage while output appears between scans.
    try:
        with pytest.raises(PublicationCommitContextError) as raised:
            _ = retain_stage(
                bound,
                output,
                names,
                rename_in_parent,
                os.fsync,
                (record,),
                (),
            )
    finally:
        os.close(stage_descriptor)
        os.close(parent_descriptor)

    # Then: both rounds ran and the terminal output identity is surfaced.
    assert snapshot_calls == 2
    assert raised.value.retained == (record,)
    output_records = tuple(
        transient
        for transient in raised.value.transient
        if transient.leaf_name == output.name
    )
    assert len(output_records) == 1
    assert output_records[0].identity == _identity(output)
    assert_live_retained_records(raised.value.retained)


__all__: tuple[str, ...] = ()
