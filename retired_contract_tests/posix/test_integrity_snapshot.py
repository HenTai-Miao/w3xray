"""Deterministic integrity-snapshot construction and parsing contracts."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from gametool.integrity_snapshot import (
    IntegritySnapshotError,
    SnapshotRoot,
    build_integrity_snapshot,
    format_integrity_snapshot,
    parse_integrity_snapshot,
)


def test_integrity_snapshot_records_path_size_mtime_and_content(
    tmp_path: Path,
) -> None:
    root = tmp_path / "maps"
    root.mkdir()
    source = root / "a.w3x"
    source.write_bytes(b"map")
    os.utime(
        source,
        ns=(
            1_700_000_000_000_000_000,
            1_700_000_000_000_000_000,
        ),
    )

    snapshot = build_integrity_snapshot((SnapshotRoot("maps", root),))

    entry = snapshot.roots[0].entries[0]
    assert entry.relative_path == "a.w3x"
    assert entry.size == 3
    assert entry.mtime_ns == 1_700_000_000_000_000_000
    assert entry.sha256 == hashlib.sha256(b"map").hexdigest()
    assert parse_integrity_snapshot(format_integrity_snapshot(snapshot)) == snapshot


def test_integrity_snapshot_rejects_symlinks_and_overlapping_roots(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    child = root / "child"
    child.mkdir(parents=True)
    (root / "linked").symlink_to(tmp_path / "outside")

    with pytest.raises(IntegritySnapshotError):
        build_integrity_snapshot((SnapshotRoot("root", root),))
    (root / "linked").unlink()
    with pytest.raises(IntegritySnapshotError):
        build_integrity_snapshot(
            (SnapshotRoot("root", root), SnapshotRoot("child", child))
        )
