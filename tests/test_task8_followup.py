"""Follow-up regressions from the independent Task 8 review."""

from __future__ import annotations

import hashlib
import struct
from contextlib import nullcontext
from pathlib import Path

from tests.test_terrain import _w3e_header
from w3xtool.cli_detail_summary import (
    iter_gameplay_constant_summary_lines,
    iter_slk_summary_lines,
)
from w3xtool.cli_structure import iter_map_structure_summary_lines
from w3xtool.cli_terrain import iter_terrain_summary_lines
from w3xtool.gui_archive_reports import build_archive_blocks
from w3xtool.map_data import MapData
from w3xtool.map_identity import build_map_identity


class _Archive:
    path = "attached.w3x"

    def __init__(self, files: dict[str, bytes], raw: bytes = b"attached archive") -> None:
        self.files = files
        self._data = raw

    def has_file(self, name: str) -> bool:
        return name in self.files

    def read_file(self, name: str) -> bytes:
        return self.files[name]

    def list_files(self) -> list[str]:
        return list(self.files)

    def close(self) -> None:
        return None


class _Source:
    path = "attached.w3x"

    def __init__(self, archive: _Archive) -> None:
        self.archive = archive

    def open(self):
        return nullcontext(self.archive)

    def close(self) -> None:
        return None


def _report_map() -> MapData:
    slk = (
        b"ID\nB;Y2;X2\n"
        b'C;X1;Y1;K"unitID"\n'
        b'C;X2;Y1;K"Name"\n'
        b'C;X1;Y2;K"hfoo"\n'
        b'C;X2;Y2;K"Footman"\n'
    )
    files = {
        "war3map.w3e": _w3e_header() + b"\x00" * 16,
        "war3map.w3r": b"W3R!" + struct.pack("<ii", 5, 2),
        "war3map.wpm": b"MP3W" + struct.pack("<iii", 0, 2, 2) + b"\x00" * 4,
        "Units\\UnitData.slk": slk,
        "war3mapMisc.txt": b"[Misc]\nHeroMaxLevel=20\n",
    }
    return MapData(
        path="Maps\\Chapter1.w3x",
        name="Chapter 1",
        all_files=list(files),
        archive_source=_Source(_Archive(files)),
    )


def test_gui_archive_blocks_reopen_campaign_child_source() -> None:
    # Given: an active campaign child has a logical path and attached archive.
    md = _report_map()

    # When: the GUI builds archive-backed analysis blocks.
    blocks = build_archive_blocks(md)

    # Then: terrain, SLK and gameplay data remain visible for the child.
    assert {"地形", "SLK", "游戏常数"} <= {block.title for block in blocks}


def test_cli_archive_summaries_reopen_campaign_child_source() -> None:
    # Given: the same attached child source has all four CLI report domains.
    md = _report_map()

    # When: each CLI archive-backed renderer is evaluated.
    groups = (
        tuple(iter_terrain_summary_lines(md)),
        tuple(iter_map_structure_summary_lines(md)),
        tuple(iter_slk_summary_lines(md)),
        tuple(iter_gameplay_constant_summary_lines(md)),
    )

    # Then: no renderer silently drops data because the logical path is absent.
    assert any("网格" in line for line in groups[0])
    assert any("路径图" in line for line in groups[1])
    assert any("表文件" in line for line in groups[2])
    assert any("覆盖项" in line for line in groups[3])


def test_map_identity_prefers_attached_source_over_existing_logical_path(
    tmp_path: Path,
) -> None:
    # Given: an unrelated host file collides with the child's logical path.
    host_path = tmp_path / "Chapter1.w3x"
    host_path.write_bytes(b"unrelated host file")
    attached = b"owned campaign child"
    md = MapData(
        path=str(host_path),
        name="Chapter 1",
        archive_source=_Source(_Archive({}, raw=attached)),
    )

    # When: identity is built for the loaded child.
    identity = build_map_identity(md)

    # Then: the attached bytes win over the colliding host file.
    assert identity.size == len(attached)
    assert identity.sha1 == hashlib.sha1(attached).hexdigest()
