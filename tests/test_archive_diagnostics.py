"""Bounded archive-open diagnostics."""

from __future__ import annotations

import os
from pathlib import Path
import struct
import subprocess
import sys
from unittest.mock import patch

import pytest

from w3xtool import archive_diagnostics
from w3xtool.archive_diagnostics import (
    ArchiveDiagnosisKind,
    diagnose_archive_open,
)


def _header(
    *,
    version: int = 0,
    shift: int = 3,
    hash_pos: int = 32,
    block_pos: int = 96,
    hash_count: int = 4,
    block_count: int = 1,
) -> bytes:
    return struct.pack(
        "<4sIIHHIIII",
        b"MPQ\x1a",
        0x20,
        0,
        version,
        shift,
        hash_pos,
        block_pos,
        hash_count,
        block_count,
    )


def _write_chunks(
    path: Path,
    chunks: tuple[tuple[int, bytes], ...],
    *,
    total_size: int,
) -> Path:
    with path.open("wb") as handle:
        handle.truncate(total_size)
        for offset, data in chunks:
            handle.seek(offset)
            handle.write(data)
    return path


def test_hash_table_overflow_is_reported_as_structure_damage(tmp_path: Path) -> None:
    # Given: an aligned MPQ header whose hash table extends past EOF.
    path = _write_chunks(tmp_path / "hash-oob.w3x", ((0, _header(hash_count=2048)),), total_size=64)

    # When: the original file is diagnosed without opening an MPQArchive.
    diagnosis = diagnose_archive_open(str(path))

    # Then: the damaged hash boundary is reported conservatively.
    assert diagnosis.kind is ArchiveDiagnosisKind.TABLE_DAMAGE
    assert "hash" in " ".join(diagnosis.evidence).lower()


def test_truncated_signature_is_table_damage(tmp_path: Path) -> None:
    # Given: an aligned MPQ signature without a complete 32-byte header.
    path = _write_chunks(tmp_path / "truncated.w3x", ((512, b"MPQ\x1a\x00\x00"),), total_size=518)

    # When: the archive-open failure is diagnosed.
    diagnosis = diagnose_archive_open(str(path))

    # Then: a seen but truncated header is not mislabeled as no header.
    assert diagnosis.kind is ArchiveDiagnosisKind.TABLE_DAMAGE
    assert "header_truncated" in diagnosis.evidence


def test_invalid_candidate_does_not_hide_later_valid_candidate(tmp_path: Path) -> None:
    # Given: a damaged decoy at 512 and a structurally valid v0 header at 1024.
    path = _write_chunks(
        tmp_path / "decoy.w3x",
        ((512, _header(hash_count=1000)), (1024, _header())),
        total_size=4096,
    )

    # When: all bounded aligned candidates are considered.
    diagnosis = diagnose_archive_open(str(path), ValueError("open failed"))

    # Then: valid structure wins, leaving only an unexplained read/open failure.
    assert diagnosis.kind is ArchiveDiagnosisKind.READ_ERROR
    assert "candidate_offset=1024" in diagnosis.evidence
    assert "structure=valid" in diagnosis.evidence


def test_unknown_version_wins_over_earlier_invalid_candidate(tmp_path: Path) -> None:
    # Given: a damaged decoy followed by a self-consistent unsupported MPQ version.
    path = _write_chunks(
        tmp_path / "unknown-version.w3x",
        ((512, _header(block_pos=9999)), (1024, _header(version=99))),
        total_size=4096,
    )

    # When: the candidates are diagnosed.
    diagnosis = diagnose_archive_open(str(path))

    # Then: the later coherent version is classified as unsupported.
    assert diagnosis.kind is ArchiveDiagnosisKind.UNSUPPORTED
    assert "format_version=99" in diagnosis.evidence


def test_block_table_start_past_eof_is_damage(tmp_path: Path) -> None:
    # Given: a valid hash table boundary but an impossible block-table start.
    path = _write_chunks(
        tmp_path / "block-start-oob.w3x",
        ((0, _header(block_pos=9999)),),
        total_size=128,
    )

    # When: the header is diagnosed.
    diagnosis = diagnose_archive_open(str(path))

    # Then: the block-table start boundary is reported as damage.
    assert diagnosis.kind is ArchiveDiagnosisKind.TABLE_DAMAGE
    assert "block_table_start_oob" in diagnosis.evidence


def test_block_table_end_past_eof_remains_tolerated(tmp_path: Path) -> None:
    # Given: a block table starts inside the file but its declared end is inflated.
    path = _write_chunks(
        tmp_path / "block-end-oob.w3x",
        ((0, _header(block_count=4)),),
        total_size=112,
    )

    # When: the header is diagnosed after an unrelated open failure.
    diagnosis = diagnose_archive_open(str(path), ValueError("table decode failed"))

    # Then: bounded structural diagnosis does not call the tolerated tail damage.
    assert diagnosis.kind is ArchiveDiagnosisKind.READ_ERROR
    assert "structure=valid" in diagnosis.evidence


def test_no_aligned_header_is_reported(tmp_path: Path) -> None:
    # Given: a readable file with no aligned MPQ signature.
    path = tmp_path / "plain.bin"
    path.write_bytes(b"not an archive")

    # When: the file is diagnosed.
    diagnosis = diagnose_archive_open(str(path))

    # Then: it is classified as lacking an MPQ header.
    assert diagnosis.kind is ArchiveDiagnosisKind.NO_HEADER


def test_missing_and_permission_failures_are_distinct(tmp_path: Path) -> None:
    # Given: one missing path and one original-file open denied by the OS.
    missing = tmp_path / "missing.w3x"
    denied = tmp_path / "denied.w3x"

    # When: each source is diagnosed.
    missing_diagnosis = diagnose_archive_open(str(missing))
    with patch.object(
        archive_diagnostics,
        "open_regular_binary",
        side_effect=PermissionError(13, "denied"),
    ):
        denied_diagnosis = diagnose_archive_open(str(denied))

    # Then: callers can distinguish absence from source permission failure.
    assert missing_diagnosis.kind is ArchiveDiagnosisKind.MISSING
    assert denied_diagnosis.kind is ArchiveDiagnosisKind.PERMISSION


def test_directory_read_failure_is_conservative(tmp_path: Path) -> None:
    # Given: an existing path that cannot be read as a regular archive file.
    path = tmp_path / "directory.w3x"
    path.mkdir()

    # When: it is diagnosed.
    diagnosis = diagnose_archive_open(str(path))

    # Then: the helper reports an OS read failure without claiming damage.
    assert diagnosis.kind is ArchiveDiagnosisKind.READ_ERROR


def test_probe_uses_only_bounded_header_reads(tmp_path: Path) -> None:
    # Given: a file with a valid header and a payload that must not be scanned.
    path = _write_chunks(tmp_path / "bounded.w3x", ((0, _header()),), total_size=2 * 1024 * 1024)
    real_open = archive_diagnostics.open_regular_binary
    read_sizes: list[int] = []

    class TrackingReader:
        def __init__(self, handle) -> None:
            self._handle = handle

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return self._handle.__exit__(exc_type, exc, traceback)

        def fileno(self) -> int:
            return self._handle.fileno()

        def seek(self, offset: int) -> int:
            return self._handle.seek(offset)

        def read(self, size: int = -1) -> bytes:
            read_sizes.append(size)
            return self._handle.read(size)

    def tracking_open(source: str):
        handle, size = real_open(source)
        return TrackingReader(handle), size

    # When: the helper probes the file.
    with patch.object(
        archive_diagnostics,
        "open_regular_binary",
        side_effect=tracking_open,
    ):
        diagnose_archive_open(str(path))

    # Then: no whole-file or payload-sized read occurs.
    assert read_sizes
    assert set(read_sizes) == {32}
    assert sum(read_sizes) <= 32 * ((2 * 1024 * 1024) // 512 + 1)


def test_header_beyond_sixteen_mib_scan_window_is_ignored(tmp_path: Path) -> None:
    # Given: a sparse file whose only MPQ header begins at the 16 MiB boundary.
    scan_limit = 16 * 1024 * 1024
    path = _write_chunks(
        tmp_path / "late-header.w3x",
        ((scan_limit, _header()),),
        total_size=scan_limit + 4096,
    )

    # When: bounded diagnosis scans the original file.
    diagnosis = diagnose_archive_open(str(path))

    # Then: data beyond the bounded search window is not inspected.
    assert diagnosis.kind is ArchiveDiagnosisKind.NO_HEADER


def test_fifo_diagnosis_returns_without_waiting_for_writer(tmp_path: Path) -> None:
    # Given: a FIFO path with no writer process connected.
    if not hasattr(os, "mkfifo"):
        pytest.skip("mkfifo is unavailable")
    fifo = tmp_path / "diagnostic-stream.w3x"
    os.mkfifo(fifo)
    script = "\n".join(
        (
            "import sys",
            "from w3xtool.archive_diagnostics import (",
            "    ArchiveDiagnosisKind, diagnose_archive_open,",
            ")",
            "result = diagnose_archive_open(sys.argv[1])",
            "raise SystemExit(0 if result.kind is ArchiveDiagnosisKind.READ_ERROR else 2)",
        )
    )

    # When: bounded diagnostics inspect that path in a fresh process.
    completed = subprocess.run(
        (sys.executable, "-c", script, str(fifo)),
        check=False,
        capture_output=True,
        timeout=2,
    )

    # Then: diagnosis returns conservatively without waiting for a peer.
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
