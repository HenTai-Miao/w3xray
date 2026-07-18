"""Exact retained-cache scanner bounds and stop-point contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.retained_integrity_fixture import active_cache, retained
from w3xtool import description_cache_retained_integrity as snapshot_api


def _artifact(tmp_path: Path) -> tuple[Path, Path]:
    active = active_cache(tmp_path)
    artifact = retained(active, "2", "failed-stage")
    artifact.mkdir()
    return active, artifact


def test_retained_scanner_publishes_exact_fixed_bounds() -> None:
    getattr(snapshot_api, "inspect_retained_description_caches")

    assert snapshot_api.MAX_RETAINED_FILE_BYTES == 64 * 1024 * 1024
    assert snapshot_api.MAX_RETAINED_TREE_BYTES == 512 * 1024 * 1024
    assert snapshot_api.MAX_RETAINED_FILE_COUNT == 100_000
    assert snapshot_api.MAX_RETAINED_ENTRY_COUNT == 125_000
    assert snapshot_api.MAX_RETAINED_DEPTH == 64


@pytest.mark.parametrize(
    ("size", "expected"),
    [(3, "partial-evidence"), (4, "oversized")],
)
def test_file_byte_limit_accepts_exact_and_rejects_one_more(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    size: int,
    expected: str,
) -> None:
    inspect = getattr(snapshot_api, "inspect_retained_description_caches")
    monkeypatch.setattr(snapshot_api, "MAX_RETAINED_FILE_BYTES", 3)
    active, artifact = _artifact(tmp_path)
    (artifact / "leaf").write_bytes(b"x" * size)

    report = inspect(active)

    assert report.retained[0].validation.value == expected


@pytest.mark.parametrize(
    ("sizes", "expected"),
    [((3, 3), "partial-evidence"), ((3, 4), "oversized")],
)
def test_tree_byte_limit_accepts_exact_and_rejects_one_more(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sizes: tuple[int, int],
    expected: str,
) -> None:
    inspect = getattr(snapshot_api, "inspect_retained_description_caches")
    monkeypatch.setattr(snapshot_api, "MAX_RETAINED_FILE_BYTES", 4)
    monkeypatch.setattr(snapshot_api, "MAX_RETAINED_TREE_BYTES", 6)
    active, artifact = _artifact(tmp_path)
    for index, size in enumerate(sizes):
        (artifact / str(index)).write_bytes(b"x" * size)

    report = inspect(active)

    assert report.retained[0].validation.value == expected


@pytest.mark.parametrize(
    ("limit_name", "limit", "entries", "expected"),
    [
        ("MAX_RETAINED_FILE_COUNT", 2, 2, "partial-evidence"),
        ("MAX_RETAINED_FILE_COUNT", 2, 3, "oversized"),
        ("MAX_RETAINED_ENTRY_COUNT", 2, 2, "partial-evidence"),
        ("MAX_RETAINED_ENTRY_COUNT", 2, 3, "oversized"),
    ],
)
def test_count_limits_stop_at_the_first_exceeded_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    limit_name: str,
    limit: int,
    entries: int,
    expected: str,
) -> None:
    inspect = getattr(snapshot_api, "inspect_retained_description_caches")
    monkeypatch.setattr(snapshot_api, limit_name, limit)
    active, artifact = _artifact(tmp_path)
    for index in range(entries):
        (artifact / str(index)).write_bytes(b"")

    report = inspect(active)

    assert report.retained[0].validation.value == expected


@pytest.mark.parametrize(
    ("depth", "expected"),
    [(0, "partial-evidence"), (64, "partial-evidence"), (65, "oversized")],
)
def test_retained_depth_zero_and_sixty_four_are_accepted(
    tmp_path: Path,
    depth: int,
    expected: str,
) -> None:
    inspect = getattr(snapshot_api, "inspect_retained_description_caches")
    active, artifact = _artifact(tmp_path)
    current = artifact
    for index in range(depth):
        current /= str(index)
        current.mkdir()

    report = inspect(active)

    assert report.retained[0].validation.value == expected
