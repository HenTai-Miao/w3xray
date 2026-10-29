"""W3F declarations order chapters without changing exact MPQ name identity."""

from __future__ import annotations

from pathlib import Path
import struct

import pytest

from gametool.map_loader import load_map
from gametool.mpq import MPQArchive
from tests.skin_layers_fixture import mpq, object_file


def _campaign_info(button: str, order: str) -> bytes:
    def z(value: str) -> bytes:
        return value.encode("utf-8") + b"\0"

    return b"".join(
        (
            struct.pack("<iii", 1, 1, 6000),
            *(z(value) for value in ("Campaign", "Normal", "Author", "Description")),
            struct.pack("<ii", 0, 0),
            z(""),
            z(""),
            struct.pack("<i", 0),
            z(""),
            struct.pack("<ifff4Bi", 0, 0, 0, 0, 0, 0, 0, 255, 0),
            struct.pack("<ii", 1, 1),
            z("Chapter"),
            z("Visible name"),
            z(button),
            struct.pack("<i", 1),
            z("preserved reserved text"),
            z(order),
        )
    )


def _child(code: str, label: str) -> bytes:
    return mpq(
        {
            "war3map.w3u": object_file(
                "w3u", (("unam", label, 0, 0),), code=code, base="hfoo"
            )
        },
        listed=False,
    )


@pytest.mark.parametrize("listed", (False, True))
def test_confirmed_button_path_loads_when_map_order_uses_other_slash(
    tmp_path: Path, listed: bool
) -> None:
    actual = "Maps\\Hidden.w3x"
    declared = "maps/hidden.w3x"
    w3f = _campaign_info(actual, declared)
    path = tmp_path / "campaign.w3n"
    source = mpq(
        {"war3campaign.w3f": w3f, actual: _child("H001", "retained child")},
        listed=listed,
    )
    path.write_bytes(source)
    before = path.stat()
    with MPQArchive(str(path)) as archive:
        assert archive.has_file(actual) and not archive.has_file(declared)
    md = load_map(str(path))
    try:
        assert [child.path for child in md.sub_maps] == [actual]
        assert (
            md.sub_maps[0].obj_identity_index[("单位", "H001")].name == "retained child"
        )
        assert md.w3f is not None and md.w3f.complete
        assert md.w3f.maps[0].path == declared
        assert md.w3f.map_buttons[0].path == actual
        assert md.w3f.map_order == [("preserved reserved text", declared)]
        assert md.w3f.raw_bytes == w3f
        assert not any(row.component == "campaign-child" for row in md.diagnostics)
    finally:
        md.close()
    assert path.read_bytes() == source and path.stat().st_mtime_ns == before.st_mtime_ns


@pytest.mark.parametrize("listed", (False, True))
def test_distinct_readable_slash_members_both_remain_campaign_children(
    tmp_path: Path, listed: bool
) -> None:
    backslash = "Maps\\Hidden.w3x"
    slash = "maps/hidden.w3x"
    path = tmp_path / "distinct.w3n"
    path.write_bytes(
        mpq(
            {
                "war3campaign.w3f": _campaign_info(backslash, slash),
                backslash: _child("H001", "backslash member"),
                slash: _child("H002", "slash member"),
            },
            listed=listed,
        )
    )
    with MPQArchive(str(path)) as archive:
        assert archive.has_file(backslash) and archive.has_file(slash)
        assert archive.block_index_of(backslash) != archive.block_index_of(slash)
        assert archive.read_file(backslash) != archive.read_file(slash)
    md = load_map(str(path))
    try:
        children = {child.path: child for child in md.sub_maps}
        assert len(md.sub_maps) == 2 and set(children) == {backslash, slash}
        assert md.sub_maps[0].path == slash
        assert (
            children[backslash].obj_identity_index[("单位", "H001")].name
            == "backslash member"
        )
        assert (
            children[slash].obj_identity_index[("单位", "H002")].name == "slash member"
        )
        assert md.w3f is not None and md.w3f.maps[0].path == slash
    finally:
        md.close()


def test_missing_declared_child_remains_a_read_diagnostic(tmp_path: Path) -> None:
    path = tmp_path / "missing.w3n"
    declared = "maps/missing.w3x"
    path.write_bytes(
        mpq(
            {"war3campaign.w3f": _campaign_info("Maps\\Missing.w3x", declared)},
            listed=False,
        )
    )
    md = load_map(str(path))
    try:
        assert not md.sub_maps
        assert any(
            row.component == "campaign-child"
            and row.source == declared
            and row.exception_type == "KeyError"
            for row in md.diagnostics
        )
        assert md.w3f is not None and md.w3f.maps[0].path == declared
    finally:
        md.close()
