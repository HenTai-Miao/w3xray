"""Warcraft III game-data directory source tests."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from w3xtool.game_data_source import DirectoryDataSource, probe_game_data_path
from w3xtool.icons import IconResolver


class GameDataSourceTest(unittest.TestCase):
    def test_directory_source_resolves_reforged_w3mod_prefix(self) -> None:
        # Given: Reforged client data was exported with the war3.w3mod namespace.
        with tempfile.TemporaryDirectory() as root:
            texture_dir = os.path.join(
                root,
                "war3.w3mod",
                "ReplaceableTextures",
                "CommandButtons",
            )
            os.makedirs(texture_dir)
            texture_path = os.path.join(texture_dir, "BTNHero.blp")
            with open(texture_path, "wb") as handle:
                handle.write(b"BLP1hero")

            # When: the runtime data source resolves a classic game path.
            source = DirectoryDataSource(root)

            # Then: namespace prefixes, slash style and case differences do not matter.
            self.assertTrue(source.has_file("ReplaceableTextures\\CommandButtons\\BTNHero.blp"))
            self.assertEqual(
                source.read_file("replaceabletextures/commandbuttons/btnhero.blp"),
                b"BLP1hero",
            )

    def test_probe_marks_native_casc_install_as_needing_export(self) -> None:
        # Given: a raw Reforged install uses CASC indexes rather than plain files.
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "Data", "data"))
            with open(os.path.join(root, ".build.info"), "w", encoding="utf-8") as handle:
                handle.write("BuildKey\n")
            with open(os.path.join(root, "Data", "data", "data.000"), "wb") as handle:
                handle.write(b"casc")
            with open(os.path.join(root, "Data", "data", "0000000000000000.idx"), "wb") as handle:
                handle.write(b"idx")

            # When: the path is probed.
            result = probe_game_data_path(root)

            # Then: the app can explain why direct reads are unavailable.
            self.assertEqual(result.kind, "native_casc")
            self.assertFalse(result.is_readable)
            self.assertIn("先导出", result.message)

    def test_icon_resolver_reads_blp_from_reforged_exported_data_dir(self) -> None:
        # Given: an exported Reforged data directory contains a base-game icon.
        with tempfile.TemporaryDirectory() as root, tempfile.NamedTemporaryFile(suffix=".w3x") as map_file:
            texture_dir = os.path.join(root, "war3.w3mod", "ReplaceableTextures", "CommandButtons")
            os.makedirs(texture_dir)
            with open(os.path.join(texture_dir, "BTNHero.blp"), "wb") as handle:
                handle.write(b"BLP1hero")

            decoded = Image.new("RGBA", (16, 16), (1, 2, 3, 255))

            # When: the resolver is configured with that data directory.
            with patch("w3xtool.icons.decode_blp", return_value=decoded) as decode:
                resolver = IconResolver(map_file.name, game_data_path=root)
                image = resolver.get_image("ReplaceableTextures\\CommandButtons\\BTNHero.blp")
                resolver.close()

            # Then: map objects can display icons from Reforged extracted data.
            self.assertIs(image, decoded)
            decode.assert_called_once_with(b"BLP1hero")


if __name__ == "__main__":
    unittest.main()
