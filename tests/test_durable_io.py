"""Durability guarantees for staged file and directory publication."""

from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

from w3xtool import durable_io, safe_output, safe_output_publication
from w3xtool.safe_output import write_bytes_safely
from w3xtool.safe_output_chunk_writer import write_chunks_to_descriptor
from w3xtool.safe_output_models import SafeWriteStatus


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
    assert not tuple(tmp_path.glob(".w3xray-backup-*.tmp"))


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
    assert not tuple(tmp_path.glob(".w3xray-stage-*.tmp"))


def test_path_fallback_restores_destination_when_directory_sync_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the Windows-style path fallback and an existing destination.
    destination = tmp_path / "state.json"
    destination.write_bytes(b"old")
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

    # Then: fallback publication restores the prior target.
    assert result.status is SafeWriteStatus.FAILED
    assert destination.read_bytes() == b"old"
    assert sync_calls == 3
    assert not tuple(tmp_path.glob(".w3xray-backup-*.tmp"))
