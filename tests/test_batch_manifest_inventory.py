"""Peak memory bounds for manifest report snapshots."""

from __future__ import annotations

from pathlib import Path

import pytest

import w3xtool.batch_manifest_inventory as manifest_inventory


def test_report_snapshot_rejects_before_exceeding_aggregate_peak(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: either report fits the per-file cap, but both exceed the total budget.
    (tmp_path / "图标未解析.tsv").write_bytes(b"a" * 6)
    (tmp_path / "图标索引.tsv").write_bytes(b"b" * 6)
    monkeypatch.setattr(manifest_inventory, "_MAX_REPORT_BYTES", 10)
    monkeypatch.setattr(
        manifest_inventory,
        "_MAX_TOTAL_REPORT_BYTES",
        10,
        raising=False,
    )
    bounded_read = manifest_inventory.read_bounded_regular_file
    attempted_limits: list[int] = []
    successful_bytes = 0

    def observe_read(path: Path, max_size: int):
        nonlocal successful_bytes
        attempted_limits.append(max_size)
        content, identity = bounded_read(path, max_size)
        successful_bytes += len(content)
        return content, identity

    monkeypatch.setattr(
        manifest_inventory,
        "read_bounded_regular_file",
        observe_read,
    )

    # When / Then: the second payload is rejected against remaining budget.
    with pytest.raises(
        manifest_inventory.ManifestInventoryError,
        match="size limit|too large|exceed",
    ):
        manifest_inventory.snapshot_artifact_inventory(tmp_path)
    assert attempted_limits == [10, 4]
    assert successful_bytes == 6
