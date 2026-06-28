"""war3map.w3e 地形头解析。"""
import struct
import unittest

from w3xtool.terrain import (
    TerrainBounds,
    TerrainInfo,
    TerrainPointSummary,
    parse_w3e_header,
    terrain_info_from_map_path,
)
from w3xtool.terrain_tiles import describe_terrain_tile, format_terrain_tile_list


def _w3e_header() -> bytes:
    return (
        b"W3E!"
        + struct.pack("<i", 11)
        + b"L"
        + struct.pack("<i", 1)
        + struct.pack("<i", 2)
        + b"Ldrt"
        + b"Ldro"
        + struct.pack("<i", 1)
        + b"CLdi"
        + struct.pack("<ii", 65, 33)
    )


def _tile(height, water, flags=0, texture=1, cliff_texture=0, cliff_level=0):
    texture_and_flags = (flags << 4) | texture
    cliff_data = (cliff_texture << 4) | cliff_level
    return struct.pack("<HHBBB", height, water, texture_and_flags, 0, cliff_data)


def _w3e_with_tiles() -> bytes:
    return (
        b"W3E!"
        + struct.pack("<i", 11)
        + b"L"
        + struct.pack("<i", 0)
        + struct.pack("<i", 1)
        + b"Ldrt"
        + struct.pack("<i", 0)
        + struct.pack("<ii", 2, 2)
        + struct.pack("<ff", -128.0, -128.0)
        + _tile(8192, 8192 | 0x4000, 0x01, texture=0, cliff_texture=1, cliff_level=0)
        + _tile(8704, 8704, 0x04)
        + _tile(7680, 8192, 0x02)
        + _tile(9216, 9216, 0x08, texture=0, cliff_texture=1, cliff_level=2)
    )


class TerrainTest(unittest.TestCase):
    def test_parse_w3e_header_reads_tile_sets_and_size(self):
        # Given: a minimal valid W3E header.
        data = _w3e_header() + b"\x00" * 16

        # When: the terrain header is parsed.
        info = parse_w3e_header(data)

        # Then: tile and grid metadata is returned.
        self.assertEqual(
            info,
            TerrainInfo(
                version=11,
                base_tileset="L",
                custom_tilesets=True,
                ground_tiles=("Ldrt", "Ldro"),
                cliff_tiles=("CLdi",),
                width=65,
                height=33,
                bounds=TerrainBounds(left=0.0, bottom=0.0, right=8192.0, top=4096.0),
            ),
        )

    def test_parse_w3e_header_rejects_invalid_magic(self):
        self.assertIsNone(parse_w3e_header(b"nope"))

    def test_parse_w3e_header_rejects_truncated_tile_table(self):
        data = _w3e_header()[:-2]

        self.assertIsNone(parse_w3e_header(data))

    def test_parse_w3e_header_reads_tilepoint_summary_when_present(self):
        # Given: a W3E file with a complete 2x2 terrain tilepoint payload.
        data = _w3e_with_tiles()

        # When: the terrain data is parsed.
        info = parse_w3e_header(data)

        # Then: height, water and terrain flag statistics are available.
        self.assertIsNotNone(info)
        assert info is not None
        self.assertEqual(
            info.point_summary,
            TerrainPointSummary(
                cells=4,
                min_height=-1.0,
                max_height=2.0,
                min_water_height=0.0,
                max_water_height=2.0,
                ramp=1,
                blighted=1,
                water=1,
                boundary=1,
                edge=1,
                texture_counts=((0, 2), (1, 2)),
                cliff_texture_counts=((0, 2), (1, 2)),
                cliff_level_counts=((0, 3), (2, 1)),
            ),
        )
        self.assertEqual(
            info.bounds,
            TerrainBounds(left=-128.0, bottom=-128.0, right=0.0, top=0.0),
        )

    def test_terrain_info_from_missing_map_returns_none(self):
        self.assertIsNone(terrain_info_from_map_path("missing-test-map.w3x"))

    def test_describe_terrain_tile_adds_editor_name_and_texture_path(self):
        # Given: a standard Lordaeron Summer terrain tile id.
        # When: the tile id is described.
        tile = describe_terrain_tile("Ldrt")

        # Then: both the localized editor label and texture path are returned.
        self.assertEqual(tile.tile_id, "Ldrt")
        self.assertEqual(tile.label, "洛丹伦的夏天 - 泥地")
        self.assertEqual(tile.path, "TerrainArt\\LordaeronSummer\\Lords_Dirt.blp")

    def test_format_terrain_tile_list_keeps_unknown_ids_visible(self):
        # Given: a mix of known and unknown tile ids.
        # When: the list is formatted for summaries.
        text = format_terrain_tile_list(("Ldrt", "????"))

        # Then: known ids are enriched and unknown ids remain inspectable.
        self.assertIn("Ldrt(洛丹伦的夏天 - 泥地", text)
        self.assertIn("TerrainArt\\LordaeronSummer\\Lords_Dirt.blp", text)
        self.assertIn("????", text)


if __name__ == "__main__":
    unittest.main()
