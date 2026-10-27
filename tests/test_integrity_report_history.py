"""Immutable history contracts for overwritten integrity reports."""

from __future__ import annotations

import hashlib
from pathlib import Path

from gametool.integrity_cli import run_integrity_cli
from gametool.safe_output import write_bytes_safely
from gametool.safe_output_models import SafeWriteStatus


_HISTORY_ROOT = ".gamexray-integrity-history"
_MANIFEST_NAME = "历史清单.json"
_REPORT_NAME = "report.json"


def _snapshot(root: Path, output: Path) -> int:
    return run_integrity_cli(
        ("snapshot", "--root", f"root={root}", "--output", str(output))
    )


def _generations(output: Path) -> tuple[Path, ...]:
    key = hashlib.sha256(output.name.encode("utf-8")).hexdigest()
    bucket = output.parent / _HISTORY_ROOT / key
    return tuple(
        sorted(
            (path for path in bucket.iterdir() if not path.name.startswith(".")),
            key=lambda path: path.name,
        )
    )


def test_generic_safe_writer_keeps_plain_atomic_overwrite_responsibility(
    tmp_path: Path,
) -> None:
    # Given: a normal non-integrity output written through the shared writer.
    first = write_bytes_safely(str(tmp_path), "ordinary.bin", b"first")

    # When: the same ordinary output is atomically replaced.
    second = write_bytes_safely(str(tmp_path), "ordinary.bin", b"second")

    # Then: it does not acquire integrity-report history semantics.
    assert first.status is SafeWriteStatus.WRITTEN
    assert second.status is SafeWriteStatus.WRITTEN
    assert (tmp_path / "ordinary.bin").read_bytes() == b"second"
    assert not (tmp_path / _HISTORY_ROOT).exists()
