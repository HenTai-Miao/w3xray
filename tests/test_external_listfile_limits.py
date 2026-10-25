"""Full listfile reads and former count/line boundary regressions."""

from __future__ import annotations

from pathlib import Path

import pytest

from gametool import external_listfile
from gametool.external_listfile import read_external_listfile


def test_external_listfile_reads_every_chunk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gametool import bounded_file

    monkeypatch.setattr(bounded_file, "_READ_CHUNK_BYTES", 3)
    path = tmp_path / "listfile.txt"
    path.write_bytes(b"war3map.j\r\nTextures\\last.blp\n")
    assert read_external_listfile(str(path)) == ("war3map.j", "Textures\\last.blp")


def test_external_listfile_honors_an_explicit_embedding_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "listfile.txt"
    path.write_bytes(b"war3map.j\n")
    monkeypatch.setattr(external_listfile, "MAX_EXTERNAL_LISTFILE_BYTES", 4)
    assert read_external_listfile(str(path)) == ()


def test_external_listfile_keeps_lines_above_the_old_character_ceiling(
    tmp_path: Path,
) -> None:
    path = tmp_path / "long.txt"
    path.write_bytes(b"x" * 65537 + b"\n")
    assert read_external_listfile(str(path)) == ("x" * 65537,)


def test_external_listfile_keeps_entries_above_the_old_count_ceiling(
    tmp_path: Path,
) -> None:
    path = tmp_path / "many.txt"
    path.write_bytes(b"x\n" * 10_000_001)
    names = read_external_listfile(str(path))
    assert len(names) == 10_000_001
    assert names[0] == names[-1] == "x"
