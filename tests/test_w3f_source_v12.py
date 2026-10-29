"""Independent verified W3F layout bytes reach hidden campaign child loading."""

from __future__ import annotations

import base64
import json
from pathlib import Path
import struct

import pytest

from gametool.api import load_map
from gametool.map_metadata_exports import format_map_metadata_evidence
from gametool.mpq import MPQArchive
from gametool.w3f import (
    W3fDiagnostic,
    W3fInfo,
    parse_w3f,
    parse_w3f_evidence,
    w3f_info_to_dict,
)
from tests.test_archive_export_recovery import _archive_bytes
from tests.test_object_pipeline import _binary_object


def _z(value: str) -> bytes:
    return value.encode() + b"\0"


def _w3f(version: int, *, duplicate: bool = False) -> bytes:
    # Written independently from the pinned War3Net CampaignInfo writer layout.
    raw = struct.pack("<iii", version, 5, 6000)
    raw += b"".join(
        _z(value) for value in ("TRIGSTR_1", "Normal", "Author", "Full description")
    )
    raw += struct.pack("<ii", 0, 2) + _z("Background.mdx") + _z("Minimap.blp")
    raw += struct.pack("<i", 3) + _z("Ambient.wav")
    raw += struct.pack("<ifff4Bi", 1, 0.0, 1000.0, 0.5, 1, 2, 3, 255, 1)
    if version >= 3:
        raw += struct.pack("<fffffi", 0.0, 0.0, 0.0, 1200.0, 0.75, 1)
    if version >= 2:
        raw += struct.pack("<i", 2)
    button = (
        struct.pack("<i", 1)
        + _z("Chapter")
        + _z("Visible name")
        + _z("Maps\\Hidden.w3x")
    )
    raw += struct.pack("<i", 2 if duplicate else 1) + button * (2 if duplicate else 1)
    raw += struct.pack("<i", 1) + _z("retained reserved value") + _z("maps/hidden.w3x")
    return raw


def _partition(info: W3fInfo) -> None:
    cursor = 0
    for row in info.byte_fields:
        assert row.offset == cursor
        assert row.raw_bytes == info.raw_bytes[row.offset : row.end_offset]
        cursor = row.end_offset
    assert cursor == info.consumed_bytes
    assert info.unconsumed_data == info.raw_bytes[cursor:]


@pytest.mark.parametrize("version", [1, 2, 3])
def test_all_verified_versions_keep_layout_fields_and_every_declared_row(
    version: int,
) -> None:
    raw = _w3f(version, duplicate=True)
    info = parse_w3f_evidence(raw, {1: "Confirmed title"})
    assert info.complete and info.header_complete and info.maps_complete
    assert not info.diagnostics and info.diagnostic is None
    assert info.name == "Confirmed title"
    assert info.background_version == (None if version == 1 else 2)
    assert len(info.map_buttons) == 2
    assert info.map_order == [("retained reserved value", "maps/hidden.w3x")]
    assert [row.path for row in info.maps] == ["maps/hidden.w3x"]
    assert info.maps[0].display_name == "Visible name"
    assert info.fog_height_start == (0.0 if version == 3 else None)
    assert info.fog_linear_end == (1200.0 if version == 3 else None)
    assert info.fog_max_opacity == (0.75 if version == 3 else None)
    assert info.fog_draw_over_sky == (1 if version == 3 else None)
    assert info.raw_bytes == raw
    assert info.consumed_bytes == len(raw)
    encoded = json.loads(json.dumps(w3f_info_to_dict(info), allow_nan=False))
    assert base64.b64decode(encoded["raw_bytes_base64"]) == raw
    _partition(info)


def test_every_truncation_retains_exact_consumed_and_unconsumed_bytes() -> None:
    complete = _w3f(3)
    for end in range(len(complete)):
        raw = complete[:end]
        info = parse_w3f_evidence(raw)
        assert not info.complete and not info.maps_complete, end
        assert info.diagnostic == W3fDiagnostic.TRUNCATED, end
        assert info.raw_bytes == raw
        assert 0 <= info.consumed_bytes <= len(raw)
        _partition(info)
        if not info.header_complete:
            assert parse_w3f(raw) is None


@pytest.mark.parametrize("version", [-1, 0, 4, 2_147_483_647])
def test_unknown_versions_do_not_borrow_a_known_layout(version: int) -> None:
    raw = struct.pack("<i", version) + _w3f(3)[4:]
    info = parse_w3f_evidence(raw)
    assert info.maps == [] and not info.complete and not info.header_complete
    assert info.consumed_bytes == 4
    assert info.unconsumed_data == raw[4:]
    assert info.diagnostic == W3fDiagnostic.UNSUPPORTED_VERSION
    assert info.diagnostics[0].offset == 0
    _partition(info)


def test_trailing_bytes_and_nonfinite_fog_keep_diagnostics_and_raw_evidence() -> None:
    original = _w3f(3)
    parsed = parse_w3f_evidence(original)
    fog = next(row for row in parsed.byte_fields if row.name == "fog_max_opacity")
    raw = (
        original[: fog.offset]
        + struct.pack("<I", 0x7FC00007)
        + original[fog.end_offset :]
        + b"unrecognized\x00tail"
    )
    info = parse_w3f_evidence(raw)
    assert info.maps_complete and not info.complete
    assert [row.code for row in info.diagnostics] == [
        W3fDiagnostic.INVALID_VALUE,
        W3fDiagnostic.TRAILING_DATA,
    ]
    assert info.unconsumed_data == b"unrecognized\x00tail"
    assert info.diagnostics[0].offset == fog.offset
    encoded = json.loads(json.dumps(w3f_info_to_dict(info), allow_nan=False))
    assert encoded["fog_max_opacity"] == "nan"
    assert base64.b64decode(encoded["raw_bytes_base64"]) == raw
    _partition(info)


def test_real_listfile_stripped_v3_campaign_discovers_and_loads_declared_child(
    tmp_path: Path,
) -> None:
    child = _archive_bytes(
        [
            (
                "war3map.w3u",
                0,
                0,
                _binary_object("hfoo", "H001", (("unam", "Hidden chapter unit"),)),
                False,
            ),
        ]
    )
    w3f = _w3f(3)
    wts = b"\xff\xfe" + "STRING 1\n{\nCampaign title\n}\n".encode("utf-16-le")
    raw = _archive_bytes(
        [
            ("war3campaign.w3f", 0, 0, w3f, False),
            ("war3campaign.wts", 0, 0, wts, False),
            ("Maps\\Hidden.w3x", 0, 0, child, False),
        ]
    )
    path = tmp_path / "campaign.w3n"
    path.write_bytes(raw)
    before = path.stat()
    with MPQArchive(str(path)) as archive:
        assert not archive.has_file("(listfile)")
        assert not any(
            name.lower().endswith("hidden.w3x") for name in archive.list_files()
        )
    md = load_map(str(path))
    try:
        assert md.name == "Campaign title"
        assert md.w3f is not None and md.w3f.complete
        assert len(md.sub_maps) == 1
        assert md.sub_maps[0].path == "Maps\\Hidden.w3x"
        assert (
            md.sub_maps[0].obj_identity_index[("单位", "H001")].name
            == "Hidden chapter unit"
        )
        exported = json.loads(format_map_metadata_evidence(md))
        assert exported["campaign_complete"]
        assert base64.b64decode(exported["w3f"]["raw_bytes_base64"]) == w3f
        assert exported["w3f"]["maps"][0]["path"] == "maps/hidden.w3x"
        assert not exported["campaign_diagnostics"]
    finally:
        md.close()
    assert path.read_bytes() == raw
    assert path.stat().st_mtime_ns == before.st_mtime_ns


@pytest.mark.parametrize(
    "raw", [b"", b"\x03\x00", b"\x03\0\0\0\x01", struct.pack("<i", 4) + b"unverified"]
)
def test_real_loading_and_json_keep_even_damaged_campaign_headers(
    tmp_path: Path, raw: bytes
) -> None:
    path = tmp_path / "damaged.w3n"
    path.write_bytes(_archive_bytes([("war3campaign.w3f", 0, 0, raw, False)]))
    md = load_map(str(path))
    try:
        assert md.w3f is not None and not md.w3f.complete
        assert md.w3f.raw_bytes == raw
        assert md.sub_maps == []
        exported = json.loads(format_map_metadata_evidence(md))
        assert not exported["campaign_complete"]
        assert base64.b64decode(exported["w3f"]["raw_bytes_base64"]) == raw
        assert exported["campaign_diagnostics"]
    finally:
        md.close()
