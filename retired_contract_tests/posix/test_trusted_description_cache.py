"""Validation tests for owned trusted-description cache generations."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.description_cache_migration_fixture import (
    LEGACY_RELATIVE,
)
from tests.source_parent_swap_fixture import swapping_open
from tests.trusted_description_cache_fixture import (
    published_cache,
)
from gametool import anchored_source
from gametool.trusted_description_cache import (
    TrustedDescriptionCacheError,
    load_trusted_description_cache,
)


_REQUIRES_ANCHORED_SOURCE = pytest.mark.skipif(
    not anchored_source._ANCHORED_OPEN_AVAILABLE,
    reason="requires descriptor-relative no-follow source reads",
)


@_REQUIRES_ANCHORED_SOURCE
def test_trusted_replay_rejects_intermediate_source_parent_swapped_during_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: an owned cache whose source parent becomes a symlink at open time.
    root = published_cache(tmp_path)
    report = tmp_path / "legacy-output" / LEGACY_RELATIVE / "对象描述.tsv"
    source_parent = tmp_path / "legacy-output" / "地图"
    moved_parent = tmp_path / "moved-map-parent"
    events: list[str] = []
    monkeypatch.setattr(
        os,
        "open",
        swapping_open(os.open, source_parent, moved_parent, report, events),
    )

    # When / Then: replay must walk from its held root fd without following it.
    with pytest.raises(TrustedDescriptionCacheError, match="source|symlink|regular"):
        _ = load_trusted_description_cache(root)
    assert events == ["parent swapped"]
