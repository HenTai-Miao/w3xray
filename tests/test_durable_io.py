"""Durability guarantees for staged file and directory publication."""

from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

from gametool import durable_io, safe_output
from gametool.safe_output import write_bytes_safely
from gametool.safe_output_anchored import ANCHORED_WRITES_AVAILABLE
from gametool.safe_output_chunk_writer import write_chunks_to_descriptor
from gametool.safe_output_models import SafeWriteStatus


_REQUIRES_ANCHORED_WRITES = pytest.mark.skipif(
    not ANCHORED_WRITES_AVAILABLE,
    reason="requires descriptor-anchored publication",
)


def test_chunk_writer_syncs_complete_stage_before_return(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a raw staged descriptor and an observable fsync boundary.
    calls: list[int] = []
    monkeypatch.setattr(durable_io.os, "fsync", calls.append)
    descriptor = os.open(tmp_path / "stage", os.O_CREAT | os.O_WRONLY, 0o600)

    # When: all chunks are written successfully.
    try:
        size = write_chunks_to_descriptor(descriptor, (b"a", b"b"))
    finally:
        os.close(descriptor)

    # Then: bytes are durable before the writer reports success.
    assert size == 2
    assert calls == [descriptor]


def test_directory_sync_rejects_non_windows_io_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: directory fsync fails with a real storage error.
    def fail_sync(_descriptor: int) -> None:
        raise OSError(errno.EIO, "simulated directory sync failure")

    monkeypatch.setattr(durable_io.os, "fsync", fail_sync)

    # When / Then: the durability failure is never hidden.
    with pytest.raises(OSError, match="directory sync failure"):
        durable_io.sync_directory_descriptor(3)


def test_path_fallback_retains_recovery_evidence_when_directory_sync_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the Windows-style path fallback and an existing destination.
    destination = tmp_path / "state.json"
    destination.write_bytes(b"old")
    before = destination.stat()
    monkeypatch.setattr(safe_output, "_ANCHORED_WRITES_AVAILABLE", False)
    sync_calls = 0

    def fail_first_sync(_path: Path) -> None:
        nonlocal sync_calls
        sync_calls += 1
        if sync_calls == 2:
            raise OSError(errno.EIO, "simulated directory sync failure")

    monkeypatch.setattr(durable_io, "sync_directory", fail_first_sync)

    # When: replacement reaches its directory commit boundary.
    result = write_bytes_safely(str(tmp_path), destination.name, b"new")

    # Then: failed commit preserves both complete objects without an unsafe rename.
    assert result.status is SafeWriteStatus.FAILED
    assert "recovery retained" in result.error
    assert destination.read_bytes() == b"new"
    (backup,) = tmp_path.glob(".gamexray-backup-*.tmp")
    assert backup.read_bytes() == b"old"
    restored = backup.stat()
    assert (
        restored.st_dev,
        restored.st_ino,
        restored.st_mtime_ns,
        restored.st_size,
    ) == (
        before.st_dev,
        before.st_ino,
        before.st_mtime_ns,
        before.st_size,
    )
    assert backup.name in result.error
    assert sync_calls == 2
    assert not tuple(tmp_path.glob(".gamexray-stage-*.tmp"))
