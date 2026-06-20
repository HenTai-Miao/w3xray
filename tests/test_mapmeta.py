"""地图内部结构文件摘要。"""
import struct

from w3xtool.mapmeta import (
    MapStructureReport,
    PathingSummary,
    build_map_structure_report,
    parse_counted_structure,
    parse_structure_strings,
    parse_wpm_summary,
)


def test_parse_counted_structure_reads_header_count():
    # Given: a region-like internal file with magic/version/count.
    data = b"W3R!" + struct.pack("<ii", 5, 3) + b"\x00" * 8

    # When: the counted structure header is parsed.
    count = parse_counted_structure(data, b"W3R!")

    # Then: the declared count is returned.
    assert count == 3


def test_parse_counted_structure_rejects_bad_magic():
    # Given: bytes that are not the expected file type.
    data = b"W3C!" + struct.pack("<ii", 5, 1)

    # When / Then: no count is returned.
    assert parse_counted_structure(data, b"W3R!") is None


def test_parse_structure_strings_extracts_readable_entries():
    # Given: a counted internal file that contains zero-terminated names.
    data = (
        b"W3R!" + struct.pack("<ii", 5, 2)
        + struct.pack("<ffff", 0.0, 0.0, 128.0, 128.0)
        + "出生区域".encode("utf-8") + b"\x00"
        + b"gg_rct_Start\x00"
    )

    # When: readable strings are extracted from the structure payload.
    strings = parse_structure_strings(data, b"W3R!")

    # Then: useful labels are returned without requiring full binary decoding.
    assert strings == ("出生区域", "gg_rct_Start")


def test_parse_wpm_summary_reads_size_and_cell_count():
    # Given: a pathing map header.
    data = b"MP3W" + struct.pack("<iii", 0, 16, 8) + b"\x00" * 128

    # When: pathing metadata is parsed.
    summary = parse_wpm_summary(data)

    # Then: dimensions and cell count are available.
    assert summary == PathingSummary(width=16, height=8, cells=128)


def test_build_map_structure_report_counts_known_files():
    # Given: known structure file payloads.
    files = {
        "war3map.w3r": b"W3R!" + struct.pack("<ii", 5, 2),
        "war3map.w3c": b"W3C!" + struct.pack("<ii", 0, 4),
        "war3map.w3s": b"W3S!" + struct.pack("<ii", 1, 6),
        "war3map.wpm": b"MP3W" + struct.pack("<iii", 0, 5, 7),
    }

    # When: a structure report is built from payloads.
    report = build_map_structure_report(files)

    # Then: counts from regions/cameras/sounds/pathing are summarized.
    assert report == MapStructureReport(
        regions=2,
        cameras=4,
        sounds=6,
        pathing=PathingSummary(width=5, height=7, cells=35),
    )


def test_build_map_structure_report_includes_readable_entry_summaries():
    # Given: structure files with embedded user-facing labels and paths.
    files = {
        "war3map.w3r": b"W3R!" + struct.pack("<ii", 5, 1) + b"BossRoom\x00",
        "war3map.w3c": b"W3C!" + struct.pack("<ii", 0, 1) + b"IntroCam\x00",
        "war3map.w3s": b"W3S!" + struct.pack("<ii", 1, 1) + b"war3mapImported\\boss.mp3\x00",
    }

    # When: a structure report is built from payloads.
    report = build_map_structure_report(files)

    # Then: readable entries are available for CLI/debug summaries.
    assert report.region_strings == ("BossRoom",)
    assert report.camera_strings == ("IntroCam",)
    assert report.sound_strings == ("war3mapImported\\boss.mp3",)
