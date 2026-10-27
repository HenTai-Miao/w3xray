"""Bounded archive-open diagnostics."""

from __future__ import annotations

import os
from pathlib import Path
import struct
import subprocess
import sys

import pytest


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


def test_fifo_diagnosis_returns_without_waiting_for_writer(tmp_path: Path) -> None:
    # Given: a FIFO path with no writer process connected.
    if not hasattr(os, "mkfifo"):
        pytest.skip("mkfifo is unavailable")
    fifo = tmp_path / "diagnostic-stream.w3x"
    os.mkfifo(fifo)
    script = "\n".join(
        (
            "import sys",
            "from gametool.archive_diagnostics import (",
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
