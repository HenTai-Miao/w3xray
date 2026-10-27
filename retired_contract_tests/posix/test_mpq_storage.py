from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest


class _UnexpectedMmapError(RuntimeError):
    pass


class _MmapRejectedError(ValueError):
    pass


def test_fifo_source_is_rejected_without_waiting_for_writer(tmp_path: Path) -> None:
    # Given: a FIFO path with no writer process connected.
    if not hasattr(os, "mkfifo"):
        pytest.skip("mkfifo is unavailable")
    fifo = tmp_path / "stream.w3x"
    os.mkfifo(fifo)
    script = "\n".join(
        (
            "import sys",
            "from gametool.mpq_storage import open_mpq_backing",
            "try:",
            "    open_mpq_backing(sys.argv[1])",
            "except OSError as error:",
            "    raise SystemExit(0 if 'regular' in str(error) else 2)",
            "raise SystemExit(3)",
        )
    )

    # When: a fresh process attempts to open the FIFO as an archive.
    completed = subprocess.run(
        (sys.executable, "-c", script, str(fifo)),
        check=False,
        capture_output=True,
        timeout=2,
    )

    # Then: it rejects the non-regular descriptor without needing a peer.
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
