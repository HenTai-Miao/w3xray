"""Durability guarantees for staged file and directory publication."""

from __future__ import annotations

import errno
from pathlib import Path

import pytest

from gametool import safe_output_publication
from gametool.safe_output import write_bytes_safely
from gametool.safe_output_anchored import ANCHORED_WRITES_AVAILABLE
from gametool.safe_output_models import SafeWriteStatus


_REQUIRES_ANCHORED_WRITES = pytest.mark.skipif(
    not ANCHORED_WRITES_AVAILABLE,
    reason="requires descriptor-anchored publication",
)


@_REQUIRES_ANCHORED_WRITES
def test_existing_destination_is_restored_when_directory_sync_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a prior durable destination and a failure after replacement.
    destination = tmp_path / "state.json"
    destination.write_bytes(b"old")
    sync_calls = 0

    def fail_first_sync(_descriptor: int) -> None:
        nonlocal sync_calls
        sync_calls += 1
        if sync_calls == 1:
            raise OSError(errno.EIO, "simulated directory sync failure")

    monkeypatch.setattr(
        safe_output_publication,
        "sync_directory_descriptor",
        fail_first_sync,
    )

    # When: a new payload reaches the metadata commit boundary.
    result = write_bytes_safely(str(tmp_path), destination.name, b"new")

    # Then: publication fails and the old target is restored.
    assert result.status is SafeWriteStatus.FAILED
    assert destination.read_bytes() == b"old"
    assert sync_calls == 2
    assert not tuple(tmp_path.glob(".gamexray-backup-*.tmp"))


@_REQUIRES_ANCHORED_WRITES
def test_new_destination_is_removed_when_directory_sync_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a new output with no rollback target.
    monkeypatch.setattr(
        safe_output_publication,
        "sync_directory_descriptor",
        lambda _descriptor: (_ for _ in ()).throw(
            OSError(errno.EIO, "simulated directory sync failure")
        ),
    )

    # When: its directory metadata cannot be synchronized.
    result = write_bytes_safely(str(tmp_path), "new.json", b"new")

    # Then: no uncommitted destination is exposed as successful.
    assert result.status is SafeWriteStatus.FAILED
    assert not (tmp_path / "new.json").exists()
    assert not tuple(tmp_path.glob(".gamexray-stage-*.tmp"))
