"""Resource and filesystem boundaries reject hostile archive metadata."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pytest

from w3xtool import archive_export, safe_output
from w3xtool.knowledge_pack import write_knowledge_pack_report
from w3xtool.knowledge_results import KnowledgeWriteStatus
from w3xtool.map_data import MapData
from w3xtool.mpq_block_reader import MPQBlockError, read_mpq_block
from w3xtool.mpq_constants import FLAG_EXISTS
from w3xtool.mpq_layout import _Block
from w3xtool.safe_output_models import SafeWriteStatus
from w3xtool.slk import parse_slk


@dataclass(frozen=True, slots=True)
class _Storage:
    _data: bytes = b"x"
    archive_offset: int = 0
    sector_size: int = 4096


def test_temp_extract_name_cannot_escape_cleanup_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given: an archive-controlled map name is exactly the parent segment.
    temp_root = tmp_path / "temp"
    temp_root.mkdir()
    marker = temp_root / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    monkeypatch.setattr(archive_export.tempfile, "gettempdir", lambda: str(temp_root))

    # When: export requests a clean temporary directory.
    result = Path(archive_export.tmp_extract_dir("..", clean=True))

    # Then: cleanup remains under the owned extraction base.
    assert marker.read_text(encoding="utf-8") == "keep"
    assert result.parent.parent == temp_root
    assert result.parent.name.startswith("w3xtool提取-")
    assert result.name == "map"


def test_symlinked_pack_root_cannot_write_into_target(tmp_path: Path) -> None:
    # Given: the requested publication root is a symlink to another directory.
    outside = tmp_path / "outside"
    outside.mkdir()
    pack = tmp_path / "pack"
    pack.symlink_to(outside, target_is_directory=True)

    # When: every knowledge-pack writer runs through the shared session.
    report = write_knowledge_pack_report(MapData("fixture.w3x", "fixture"), str(pack))

    # Then: all writes are rejected and the symlink target remains untouched.
    assert report.status is KnowledgeWriteStatus.FAILED
    assert tuple(outside.iterdir()) == ()


def test_path_fallback_preserves_existing_file_on_write_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given: the Windows-style fallback has an existing destination.
    output = tmp_path / "result.bin"
    output.write_bytes(b"before")
    monkeypatch.setattr(safe_output, "_ANCHORED_WRITES_AVAILABLE", False)

    def fail_after_partial(descriptor: int, _chunks) -> int:
        _ = os.write(descriptor, b"partial")
        raise OSError("disk full")

    monkeypatch.setattr(safe_output, "write_chunks_to_descriptor", fail_after_partial)

    # When: byte publication fails after staging partial data.
    result = safe_output.write_bytes_safely(str(tmp_path), output.name, b"replacement")

    # Then: the previous destination survives intact.
    assert result.status is SafeWriteStatus.FAILED
    assert output.read_bytes() == b"before"


def test_sparse_slk_coordinate_is_rejected_before_range_expansion() -> None:
    # Given: one tiny SLK record declares a far-away column.
    text = 'ID;P\nC;X5000;Y1;K"name"\nE\n'

    # When/Then: bounds are enforced before any rectangular iteration.
    with pytest.raises(ValueError, match="SLK"):
        parse_slk(text)


def test_mpq_declared_output_size_is_bounded_before_reading() -> None:
    # Given: a one-byte block claims an implausibly large uncompressed result.
    block = _Block(0, 1, 0x7FFF_FFFF, FLAG_EXISTS)

    # When/Then: the declared size is rejected before allocation or decompression.
    with pytest.raises(MPQBlockError, match="size"):
        read_mpq_block(_Storage(), block, b"payload", None)
