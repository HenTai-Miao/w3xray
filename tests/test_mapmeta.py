"""地图内部结构文件摘要。"""
import struct

from w3xtool.mapmeta import (
    MapStructureReport,
    PathingSummary,
    ShadowSummary,
    build_map_structure_report,
    parse_counted_structure,
    parse_shd_summary,
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
    # Given: a pathing map with four cells and several pathability flags.
    cells = bytes((0x02, 0x04, 0x08 | 0x20, 0x40 | 0x80))
    data = b"MP3W" + struct.pack("<iii", 0, 2, 2) + cells

    # When: pathing metadata is parsed.
    summary = parse_wpm_summary(data)

    # Then: dimensions and pathability flag counts are available.
    assert summary == PathingSummary(
        width=2,
        height=2,
        cells=4,
        no_walk=1,
        no_fly=1,
        no_build=1,
        blight=1,
        no_water=1,
        unknown=1,
    )


def test_parse_wpm_summary_rejects_truncated_cells():
    # Given: a pathing map whose declared cell count exceeds the payload.
    data = b"MP3W" + struct.pack("<iii", 0, 3, 3) + b"\x00" * 4

    # When / Then: the truncated pathing map is treated as absent.
    assert parse_wpm_summary(data) is None


def test_parse_shd_summary_counts_shadow_cells():
    # Given: a raw shadow map with visible, hidden and unexpected cell values.
    pathing = PathingSummary(width=2, height=2, cells=4)
    data = bytes((0xFF, 0x00, 0xFF, 0x7F))

    # When: shadow map metadata is parsed with pathing dimensions.
    summary = parse_shd_summary(data, pathing)

    # Then: dimensions and shadow coverage counts are available.
    assert summary == ShadowSummary(
        width=2,
        height=2,
        cells=4,
        shadowed=2,
        unshadowed=1,
        unknown=1,
    )


def test_parse_shd_summary_rejects_mismatched_pathing_size():
    # Given: a shadow map whose raw cell count does not match pathing dimensions.
    pathing = PathingSummary(width=2, height=2, cells=4)

    # When / Then: the inconsistent shadow map is treated as absent.
    assert parse_shd_summary(b"\xFF\x00", pathing) is None


def test_build_map_structure_report_counts_known_files():
    # Given: known structure file payloads.
    files = {
        "war3map.w3r": b"W3R!" + struct.pack("<ii", 5, 2),
        "war3map.w3c": b"W3C!" + struct.pack("<ii", 0, 4),
        "war3map.w3s": b"W3S!" + struct.pack("<ii", 1, 6),
        "war3map.wpm": b"MP3W" + struct.pack("<iii", 0, 5, 7) + b"\x00" * 35,
        "war3map.shd": b"\xFF" * 10 + b"\x00" * 25,
    }

    # When: a structure report is built from payloads.
    report = build_map_structure_report(files)

    # Then: counts from regions/cameras/sounds/pathing are summarized.
    assert report == MapStructureReport(
        regions=2,
        cameras=4,
        sounds=6,
        pathing=PathingSummary(width=5, height=7, cells=35),
        shadow=ShadowSummary(width=5, height=7, cells=35, shadowed=10, unshadowed=25),
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
