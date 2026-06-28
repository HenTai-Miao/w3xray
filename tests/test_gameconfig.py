"""Warcraft III .wgc game configuration parsing."""

import struct
import tempfile
import unittest
from pathlib import Path

from w3xtool.api import MapData
from w3xtool.gameconfig import (
    find_internal_game_config_names,
    parse_game_configuration,
    read_game_configuration_file,
)
from w3xtool.map_extras import add_game_configs


def _i(value):
    return struct.pack("<i", value)


def _z(text):
    return text.encode("utf-8") + b"\x00"


def _player(slot=0, flags=0, ai_path="", ai_difficulty=1):
    return (
        _i(slot) + _i(0) + _i(0x02) + _i(slot) + _i(90)
        + _i(flags) + _i(ai_difficulty) + _z(ai_path)
    )


def _config(players):
    return (
        _i(1) + _i(0x03) + _i(4)
        + _z("Maps\\Anime\\Test.w3x")
        + _i(len(players)) + b"".join(players)
    )


class GameConfigurationParseTest(unittest.TestCase):
    def test_parse_game_configuration_fields_and_players(self):
        # Given: a v1 .wgc payload with one human and one custom-AI computer.
        data = _config((
            _player(slot=0, flags=0x01),
            _player(slot=1, flags=0x04, ai_path="AI Scripts\\rush.ai", ai_difficulty=2),
        ))

        # When: the payload is parsed.
        config = parse_game_configuration(data)

        # Then: game rules, speed and slot details are available.
        self.assertEqual(config.format_version, 1)
        self.assertEqual(config.speed_label, "400%")
        self.assertTrue(config.fog_of_war_disabled)
        self.assertTrue(config.victory_defeat_disabled)
        self.assertEqual(config.map_path, "Maps\\Anime\\Test.w3x")
        self.assertEqual(config.human_count, 1)
        self.assertEqual(config.computer_count, 1)
        self.assertEqual(config.players[1].kind_label, "电脑")
        self.assertEqual(config.players[1].ai_difficulty_label, "困难")
        self.assertTrue(config.players[1].load_custom_ai)

    def test_parse_game_configuration_supports_unicode_paths(self):
        # Given: a Reforged-style path with non-ASCII characters.
        data = _i(1) + _i(0) + _i(1) + _z("Maps\\测试\\二次元.w3x") + _i(0)

        # When: the payload is parsed.
        config = parse_game_configuration(data)

        # Then: UTF-8 path text is preserved.
        self.assertEqual(config.map_path, "Maps\\测试\\二次元.w3x")

    def test_parse_game_configuration_rejects_bad_count(self):
        # Given: a payload with an impossible player count.
        data = _i(1) + _i(0) + _i(1) + _z("x.w3x") + _i(1000)

        # When / Then: the parser rejects it instead of looping over junk.
        with self.assertRaises(ValueError):
            parse_game_configuration(data)

    def test_read_game_configuration_file(self):
        # Given: a real .wgc file on disk.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "testconfig.wgc"
            path.write_bytes(_config((_player(flags=0x01),)))

            # When: it is loaded from a path.
            config = read_game_configuration_file(path)

        # Then: the file-level helper returns the parsed configuration.
        self.assertEqual(config.map_path, "Maps\\Anime\\Test.w3x")


class GameConfigurationIntegrationTest(unittest.TestCase):
    def test_find_internal_game_config_names_dedupes_case_insensitively(self):
        names = find_internal_game_config_names(["A.wgc", "a.WGC", "war3map.j", "B.wgc"])

        self.assertEqual(names, ("A.wgc", "B.wgc"))

    def test_add_game_configs_fills_mapdata(self):
        # Given: an archive exposing an internal .wgc file.
        md = MapData(path="x.w3x", name="x")
        archive = _FakeArchive({"configs\\fast.wgc": _config((_player(flags=0x01),))})

        # When: game configs are added to MapData.
        add_game_configs(md, archive)

        # Then: the parsed config is attached with its source name.
        self.assertEqual(len(md.game_configs), 1)
        self.assertEqual(md.game_configs[0].source, "configs\\fast.wgc")
        self.assertEqual(md.game_configs[0].config.speed_label, "400%")


class _FakeArchive:
    def __init__(self, files):
        self._files = files

    def list_files(self):
        return list(self._files)

    def has_file(self, name):
        return name in self._files

    def read_file(self, name):
        return self._files[name]


if __name__ == "__main__":
    unittest.main()
