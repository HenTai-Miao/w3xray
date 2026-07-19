"""Immutable history contracts for overwritten integrity reports."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from w3xtool.integrity_cli import run_integrity_cli
from w3xtool.integrity_output_naming import probe_filesystem_naming
from w3xtool.safe_output import write_bytes_safely
from w3xtool.safe_output_models import SafeWriteStatus


_HISTORY_ROOT = ".w3xray-integrity-history"
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


def test_overwrite_moves_the_previous_report_into_a_manifested_generation(
    tmp_path: Path,
) -> None:
    # Given: one published snapshot whose exact inode and bytes are evidence.
    root = tmp_path / "maps"
    root.mkdir()
    source = root / "a.w3x"
    source.write_bytes(b"first")
    output = tmp_path / "snapshot.json"
    assert _snapshot(root, output) == 0
    previous_payload = output.read_bytes()
    previous_inode = output.stat().st_ino

    # When: a changed snapshot overwrites the same public report path.
    source.write_bytes(b"second")
    assert _snapshot(root, output) == 0

    # Then: the new report stays public and the exact prior inode is manifested.
    assert output.read_bytes() != previous_payload
    (generation,) = _generations(output)
    assert generation.name.isascii() and len(generation.name) == 32
    assert {path.name for path in generation.iterdir()} == {
        _MANIFEST_NAME,
        _REPORT_NAME,
    }
    archived = generation / _REPORT_NAME
    assert archived.read_bytes() == previous_payload
    assert archived.stat().st_ino == previous_inode
    manifest = json.loads((generation / _MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest == {
        "artifact_count": 1,
        "artifacts": [
            {
                "name": _REPORT_NAME,
                "sha256": hashlib.sha256(previous_payload).hexdigest(),
                "size": len(previous_payload),
            }
        ],
        "destination_name": output.name,
        "generation_id": generation.name,
        "schema": 1,
    }


def test_later_overwrite_appends_history_without_changing_prior_generation(
    tmp_path: Path,
) -> None:
    # Given: one overwrite has already produced an immutable history generation.
    root = tmp_path / "maps"
    root.mkdir()
    source = root / "a.w3x"
    output = tmp_path / "snapshot.json"
    source.write_bytes(b"one")
    assert _snapshot(root, output) == 0
    source.write_bytes(b"two")
    assert _snapshot(root, output) == 0
    (first_generation,) = _generations(output)
    first_inventory = {
        path.name: (path.stat().st_ino, path.read_bytes())
        for path in first_generation.iterdir()
    }

    # When: the public report is overwritten again.
    source.write_bytes(b"three")
    assert _snapshot(root, output) == 0

    # Then: one generation is appended and the earlier evidence is untouched.
    generations = _generations(output)
    assert len(generations) == 2
    assert first_generation in generations
    assert {
        path.name: (path.stat().st_ino, path.read_bytes())
        for path in first_generation.iterdir()
    } == first_inventory


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


def test_integrity_report_cannot_use_the_history_root_as_its_public_name(
    tmp_path: Path,
) -> None:
    # Given: a valid snapshot root and the reserved history-root output leaf.
    root = tmp_path / "maps"
    root.mkdir()
    (root / "a.w3x").write_bytes(b"map")
    output = tmp_path / _HISTORY_ROOT

    # When: snapshot publication binds the requested output.
    code = _snapshot(root, output)

    # Then: it rejects the namespace collision before writing any report.
    assert code == 2
    assert not output.exists()
    assert not tuple(tmp_path.glob(".w3xray-stage-*.tmp"))


def test_history_root_case_alias_follows_the_exact_parent_filesystem(
    tmp_path: Path,
) -> None:
    # Given: an output spelling that aliases the reserved root only on some filesystems.
    root = tmp_path / "maps"
    root.mkdir()
    (root / "a.w3x").write_bytes(b"map")
    output = tmp_path / _HISTORY_ROOT.upper()
    parent_descriptor = os.open(tmp_path, os.O_RDONLY)
    try:
        behavior = probe_filesystem_naming(parent_descriptor)
    finally:
        os.close(parent_descriptor)

    # When: snapshot publication binds that spelling in the exact parent.
    code = _snapshot(root, output)

    # Then: only a physically aliased spelling is reserved.
    if behavior.case_insensitive:
        assert code == 2
        assert not output.exists()
    else:
        assert code == 0
        assert output.is_file()
