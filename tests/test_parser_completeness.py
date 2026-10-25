"""Real record counts beyond former ceilings, with byte bounds still enforced."""

from __future__ import annotations

import struct
from contextlib import nullcontext
from typing import cast

import pytest

from gametool import campaign_child_loader
from gametool.gameconfig import parse_game_configuration
from gametool.load_context import MapLoadContext
from gametool.map_data import MapData
from gametool.map_archive_reader import MapArchiveReader
from gametool.mapmeta import parse_wpm_summary
from gametool.mmp import parse_preview_icons
from gametool.presentation_safety import format_user_exception, single_line_text
from gametool.slk import SlkParseError, parse_slk
from gametool.terrain import parse_w3e_header
from gametool.w3f import parse_w3f
from gametool.wtg import parse_wtg


def test_minimap_retains_more_than_one_hundred_thousand_icons() -> None:
    count = 100_001
    icon = struct.pack("<iii4B", 2, 10, 20, 0, 0, 255, 255)
    summary = parse_preview_icons(struct.pack("<ii", 0, count) + icon * count)
    assert summary.icon_count == count
    assert summary.icons[-1].x == 10
    with pytest.raises(ValueError):
        parse_preview_icons(struct.pack("<ii", 0, 2**31 - 1))


def test_sparse_slk_accepts_large_coordinates_without_dense_allocation() -> None:
    rows = parse_slk(
        'ID;PWXL;N;E\nC;X1;Y1;K"ID"\nC;X16385;Y1;K"Name"\n'
        'C;X1;Y1000001;K"I001"\nC;X16385;Y1000001;K"last"\nE\n'
    )
    assert rows == {"I001": {"Name": "last"}}
    with pytest.raises(SlkParseError):
        parse_slk("C;X0;Y1;Kbad")


def test_wgc_retains_every_encoded_player() -> None:
    count = 33
    players = b"".join(
        struct.pack("<7i", slot, 0, 0, 0, 100, 0, 0) + b"\0" for slot in range(count)
    )
    payload = (
        struct.pack("<3i", 1, 0, 3) + b"map.w3x\0" + struct.pack("<i", count) + players
    )
    config = parse_game_configuration(payload)
    assert len(config.players) == count
    assert config.players[-1].slot_id == 32


def test_wtg_retains_large_category_tables() -> None:
    count = 100_001
    category = struct.pack("<i", 42) + b"\0" + struct.pack("<i", 0)
    payload = (
        b"WTG!"
        + struct.pack("<ii", 7, count)
        + category * count
        + struct.pack("<iii", 0, 0, 0)
    )
    summary = parse_wtg(payload)
    assert summary.category_count == len(summary.categories) == count
    with pytest.raises(ValueError):
        parse_wtg(b"WTG!" + struct.pack("<ii", 7, 2**31 - 1))


def test_w3f_keeps_every_campaign_map_after_ten_thousand() -> None:
    count = 10_001
    header = struct.pack("<iii", 1, 1, 1) + b"\0" * 4
    metadata = struct.pack("<ii", 0, 0) + b"\0\0" + struct.pack("<i", 0) + b"\0"
    metadata += struct.pack("<ifff4si", 0, 0.0, 0.0, 0.0, b"\0" * 4, 0)
    entries = b"".join(
        struct.pack("<i", 1) + b"\0\0" + f"Maps\\{index:05}.w3x\0".encode()
        for index in range(count)
    )
    info = parse_w3f(
        header + metadata + struct.pack("<i", count) + entries + struct.pack("<i", 0)
    )
    assert info is not None
    assert len(info.maps) == count
    assert info.maps[-1].path == "Maps\\10000.w3x"


def test_terrain_texture_table_has_no_empirical_count_limit() -> None:
    count = 257
    payload = b"W3E!" + struct.pack("<i", 11) + b"L" + struct.pack("<ii", 1, count)
    payload += b"Ldrt" * count + struct.pack("<iii", 0, 1, 1)
    info = parse_w3e_header(payload)
    assert info is not None and len(info.ground_tiles) == count
    assert parse_w3e_header(payload[:20]) is None


def test_pathing_dimensions_are_limited_by_encoded_cells() -> None:
    width = 1_000_001
    payload = b"MP3W" + struct.pack("<iii", 0, width, 1) + b"\x02" * width
    summary = parse_wpm_summary(payload)
    assert summary is not None and summary.no_walk == width
    assert parse_wpm_summary(payload[:16]) is None


def test_display_and_error_text_preserve_their_tails() -> None:
    text = "a" * 1_000_001 + "\x00TAIL"
    assert single_line_text(text) == "a" * 1_000_001 + " TAIL"
    assert format_user_exception(ValueError("x" * 100_001 + "TAIL")).endswith("TAIL")


def test_campaign_loader_visits_every_child_without_aggregate_budgets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Archive:
        path = "fixture.w3n"
        _data = b""
        calls: list[str]

        def __init__(self) -> None:
            self.calls = []

        def has_file(self, _name: str) -> bool:
            return False

        def list_files(self) -> list[str]:
            return []

        def declared_file_size(self, _name: str) -> int:
            return 1024 * 1024

        def read_file(self, name: str) -> bytes:
            self.calls.append(name)
            return b"map"

        def close(self) -> None:
            pass

    archive = Archive()

    class Source:
        def __init__(self, _name: str, _payload: bytes) -> None:
            pass

        def open(self):
            return nullcontext(archive)

        def close(self) -> None:
            pass

    monkeypatch.setattr(campaign_child_loader, "BytesArchiveSource", Source)
    names = [f"Maps\\{index:05}.w3x" for index in range(4097)]
    parent = MapData(path=archive.path, name="campaign")

    def load_child(_archive, name: str, _depth, _shared, _context) -> MapData:
        return MapData(path=name, name=name)

    campaign_child_loader.load_campaign_children(
        parent,
        cast(MapArchiveReader, cast(object, archive)),
        names,
        0,
        MapLoadContext(),
        load_child,
    )
    assert archive.calls == names
    assert [child.path for child in parent.sub_maps] == names
    assert not parent.diagnostics
