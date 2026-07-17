"""Between-scan changes and held-stage namespace loss."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.description_cache_publication_fixture import (
    bound_stage,
    rename_in_parent,
)
from w3xtool import description_cache_publication_stage_location as stage_location
from w3xtool import description_cache_publication_stage_location_scan as location_scan
from w3xtool.description_cache_publication_errors import (
    PublicationCommitContextError,
)
from w3xtool.description_cache_publication_retention_names import RetainedCacheNames
from w3xtool.description_cache_publication_stage import BoundDescriptionCacheStage
from w3xtool.description_cache_publication_stage_retention import retain_stage


def _identity(path: Path) -> tuple[int, int]:
    details = path.stat(follow_symlinks=False)
    return details.st_dev, details.st_ino


def test_forced_locator_rejects_output_replacement_between_complete_scans(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the held stage is active before a forced locator proof begins.
    stage = tmp_path / "stage"
    output = tmp_path / "trusted"
    displaced = tmp_path / "displaced-held"
    stage.mkdir()
    names = RetainedCacheNames(tmp_path, "1" * 32)
    original_snapshot = stage_location._snapshot_locations
    scans = 0
    foreign_identity: list[tuple[int, int]] = []

    def replace_after_first_scan(
        bound: BoundDescriptionCacheStage,
        active: Path,
        retained_names: RetainedCacheNames,
    ) -> tuple[location_scan._StageLocationState, ...]:
        nonlocal scans
        snapshot = original_snapshot(bound, active, retained_names)
        scans += 1
        if scans == 1:
            active.rename(displaced)
            active.mkdir()
            foreign_identity.append(_identity(active))
        return snapshot

    monkeypatch.setattr(
        stage_location,
        "_snapshot_locations",
        replace_after_first_scan,
    )

    # When: output changes after round one on an already forced-error path.
    with bound_stage(stage) as bound:
        _ = stage.rename(output)
        held_identity = bound.stage_identity
        with pytest.raises(PublicationCommitContextError) as raised:
            _ = stage_location.locate_consumed_stage(
                bound,
                output,
                names,
                detail="forced earlier failure",
            )

    # Then: two rounds ran and current output cannot hide the displaced held object.
    assert scans == 2
    assert len(foreign_identity) == 1
    assert _identity(displaced) == held_identity
    by_name = {item.leaf_name: item for item in raised.value.transient}
    assert by_name[output.name].identity == foreign_identity[0]
    assert by_name[output.name].held_identity is None
    assert by_name[stage.name].held_identity == held_identity


def test_missing_stage_and_output_still_report_open_held_stage_identity(
    tmp_path: Path,
) -> None:
    # Given: the captured stage is moved outside every legal transaction name.
    stage = tmp_path / "stage"
    output = tmp_path / "trusted"
    displaced = tmp_path / "unlocated-held-stage"
    stage.mkdir()
    names = RetainedCacheNames(tmp_path, "2" * 32)

    # When: finalization sees both the stage and output names readably absent.
    with bound_stage(stage) as bound:
        held_identity = bound.stage_identity
        _ = stage.rename(displaced)
        with pytest.raises(PublicationCommitContextError) as raised:
            _ = retain_stage(
                bound,
                output,
                names,
                rename_in_parent,
                lambda _descriptor: None,
                (),
                (),
            )

    # Then: the still-open held identity is distinct from absent pathname evidence.
    assert _identity(displaced) == held_identity
    held = tuple(
        item for item in raised.value.transient if item.held_identity == held_identity
    )
    assert len(held) == 1
    assert held[0].leaf_name == stage.name
    assert held[0].identity is None


__all__: tuple[str, ...] = ()
