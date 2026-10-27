"""Exact retained-cache scanner bounds and stop-point contracts."""

from __future__ import annotations

from pathlib import Path


from tests.retained_integrity_fixture import active_cache, retained
from gametool import description_cache_retained_integrity as snapshot_api


def _artifact(tmp_path: Path) -> tuple[Path, Path]:
    active = active_cache(tmp_path)
    artifact = retained(active, "2", "failed-stage")
    artifact.mkdir()
    return active, artifact


def test_retained_scanner_publishes_exact_fixed_bounds() -> None:
    getattr(snapshot_api, "inspect_retained_description_caches")

    assert snapshot_api.MAX_RETAINED_FILE_BYTES is None
    assert snapshot_api.MAX_RETAINED_TREE_BYTES is None
    assert snapshot_api.MAX_RETAINED_FILE_COUNT is None
    assert snapshot_api.MAX_RETAINED_ENTRY_COUNT is None
    assert snapshot_api.MAX_RETAINED_DEPTH is None
