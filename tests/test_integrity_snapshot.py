"""Deterministic integrity-snapshot construction and parsing contracts."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from tests.windows_cache_contract_fixture import snapshot_fixture
from gametool.integrity_snapshot import (
    IntegritySnapshotError,
    SnapshotRoot,
    compare_integrity_snapshot,
    format_integrity_snapshot,
    parse_integrity_snapshot,
)


def test_integrity_comparison_reports_content_and_metadata_changes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "history"
    root.mkdir()
    source = root / "report.tsv"
    source.write_text("first", encoding="utf-8")
    before = snapshot_fixture((SnapshotRoot("history", root),))
    source.write_text("other", encoding="utf-8")
    after = snapshot_fixture((SnapshotRoot("history", root),))

    differences = compare_integrity_snapshot(before, after)

    assert differences[0].code == "file_changed"
    assert differences[0].root_label == "history"
    assert differences[0].relative_path == "report.tsv"


def test_integrity_parser_rejects_inconsistent_tree_digest(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "payload").write_bytes(b"bytes")
    snapshot = snapshot_fixture((SnapshotRoot("root", root),))
    damaged_root = replace(snapshot.roots[0], tree_sha256="0" * 64)

    with pytest.raises(IntegritySnapshotError):
        parse_integrity_snapshot(
            format_integrity_snapshot(replace(snapshot, roots=(damaged_root,)))
        )


@pytest.mark.parametrize("scope", ("snapshot", "root", "entry"))
def test_integrity_parser_rejects_duplicate_json_keys(
    tmp_path: Path,
    scope: str,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "payload").write_bytes(b"evidence")
    payload = format_integrity_snapshot(snapshot_fixture((SnapshotRoot("root", root),)))
    if scope == "snapshot":
        payload = payload.replace('  "roots":', '  "schema": 1,\n  "roots":', 1)
    elif scope == "root":
        payload = payload.replace(
            '      "entries":',
            '      "label": "root",\n      "entries":',
            1,
        )
    else:
        payload = payload.replace(
            '          "mtime_ns":',
            '          "path": "payload",\n          "mtime_ns":',
            1,
        )

    with pytest.raises(IntegritySnapshotError):
        parse_integrity_snapshot(payload)
