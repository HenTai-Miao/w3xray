"""war3map.mmp preview icon parsing."""

import struct
import unittest

from w3xtool.api import MapData
from w3xtool.mmp import parse_preview_icons


def _i(value):
    return struct.pack("<i", value)


def _icon(icon_type, x, y, red, green, blue, alpha=255):
    return _i(icon_type) + _i(x) + _i(y) + bytes((blue, green, red, alpha))


def _mmp():
    return (
        _i(0) + _i(3)
        + _icon(2, 12, 34, 255, 0, 0)
        + _icon(0, 80, 90, 255, 215, 0)
        + _icon(1, 120, 150, 80, 160, 255, 200)
    )


class PreviewIconParseTest(unittest.TestCase):
    def test_parse_preview_icons_fields_and_counts(self):
        # Given: a war3map.mmp payload with player start, gold mine and neutral building icons.
        data = _mmp()

        # When: preview icons are parsed.
        summary = parse_preview_icons(data)

        # Then: version, icon fields and per-type counts are available.
        self.assertEqual(summary.version, 0)
        self.assertEqual(summary.icon_count, 3)
        self.assertEqual(summary.player_start_count, 1)
        self.assertEqual(summary.gold_mine_count, 1)
        self.assertEqual(summary.neutral_building_count, 1)
        self.assertEqual(summary.icons[0].type_label, "玩家出生点")
        self.assertEqual(summary.icons[0].color_rgb, (255, 0, 0))
        self.assertEqual(summary.icons[2].alpha, 200)

    def test_parse_preview_icons_rejects_invalid_count(self):
        # Given: a payload declaring an impossible count.
        data = _i(0) + _i(999999999)

        # When / Then: the parser rejects it instead of looping.
        with self.assertRaises(ValueError):
            parse_preview_icons(data)

    def test_add_preview_icons_fills_mapdata(self):
        # Given: an archive exposing war3map.mmp.
        from w3xtool.map_extras import add_preview_icons

        md = MapData(path="x", name="x")
        archive = _FakeArchive({"war3map.mmp": _mmp()})

        # When: optional metadata loading runs.
        add_preview_icons(md, archive)

        # Then: parsed minimap icon metadata is attached to MapData.
        self.assertIsNotNone(md.preview_icons)
        self.assertEqual(md.preview_icons.icon_count, 3)


class _FakeArchive:
    def __init__(self, files):
        self._files = files

    def has_file(self, name):
        return name in self._files

    def read_file(self, name):
        return self._files[name]


if __name__ == "__main__":
    unittest.main()
