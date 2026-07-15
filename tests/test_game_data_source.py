"""Warcraft III game-data directory source tests."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

import pytest
from PIL import Image

import w3xtool.game_data_source as game_data_source
from w3xtool.casclib_source import CascLibProbe
from w3xtool.game_data_source import (
    DirectoryDataSource,
    open_game_data_source,
    probe_game_data_path,
)
from w3xtool.icons import IconResolver


def test_directory_exact_lookup_does_not_use_suffix_or_basename(tmp_path) -> None:
    # Given
    icon = tmp_path / "deep" / "Icons" / "BTNHero.blp"
    icon.parent.mkdir(parents=True)
    icon.write_bytes(b"BLP1")
    source = DirectoryDataSource(str(tmp_path))

    # When / Then
    assert source.has_file("BTNHero.blp")
    assert not source.has_exact_file("BTNHero.blp")
    assert source.has_exact_file(r"deep\Icons\BTNHero.blp")
    assert source.read_exact_file(r"deep\Icons\BTNHero.blp") == b"BLP1"


class GameDataSourceTest(unittest.TestCase):
    def test_discovery_uses_configured_warcraft_directory(self) -> None:
        # Given: the supported environment variable points at readable client data.
        with tempfile.TemporaryDirectory() as root:
            ui_dir = os.path.join(root, "war3.w3mod", "UI")
            os.makedirs(ui_dir)
            with open(os.path.join(ui_dir, "TriggerData.txt"), "wb") as handle:
                handle.write(b"data")

            # When: no GUI preference has been saved yet.
            with patch.dict(os.environ, {"W3XRAY_WAR3_DIR": root}, clear=False):
                found = game_data_source.discover_game_data_path()

            # Then: base object metadata and icons can be connected automatically.
            self.assertEqual(found, root)

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
            self.assertTrue(
                source.has_file("ReplaceableTextures\\CommandButtons\\BTNHero.blp")
            )
            self.assertEqual(
                source.read_file("replaceabletextures/commandbuttons/btnhero.blp"),
                b"BLP1hero",
            )

    def test_probe_marks_native_casc_install_as_needing_export(self) -> None:
        # Given: a raw Reforged install uses CASC indexes rather than plain files.
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "Data", "data"))
            with open(
                os.path.join(root, ".build.info"), "w", encoding="utf-8"
            ) as handle:
                handle.write("BuildKey\n")
            with open(os.path.join(root, "Data", "data", "data.000"), "wb") as handle:
                handle.write(b"casc")
            with open(
                os.path.join(root, "Data", "data", "0000000000000000.idx"), "wb"
            ) as handle:
                handle.write(b"idx")

            # When: the path is probed.
            result = probe_game_data_path(root)

            # Then: the app can explain why direct reads are unavailable.
            self.assertEqual(result.kind, "native_casc")
            self.assertFalse(result.is_readable)
            self.assertIn("先导出", result.message)

    def test_icon_resolver_reads_blp_from_reforged_exported_data_dir(self) -> None:
        # Given: an exported Reforged data directory contains a base-game icon.
        with (
            tempfile.TemporaryDirectory() as root,
            tempfile.NamedTemporaryFile(suffix=".w3x") as map_file,
        ):
            texture_dir = os.path.join(
                root, "war3.w3mod", "ReplaceableTextures", "CommandButtons"
            )
            os.makedirs(texture_dir)
            with open(os.path.join(texture_dir, "BTNHero.blp"), "wb") as handle:
                handle.write(b"BLP1hero")

            decoded = Image.new("RGBA", (16, 16), (1, 2, 3, 255))

            # When: the resolver is configured with that data directory.
            with patch("w3xtool.icons.decode_blp", return_value=decoded) as decode:
                resolver = IconResolver(map_file.name, game_data_path=root)
                image = resolver.get_image(
                    "ReplaceableTextures\\CommandButtons\\BTNHero.blp"
                )
                resolver.close()

            # Then: map objects can display icons from Reforged extracted data.
            self.assertIs(image, decoded)
            decode.assert_called_once_with(b"BLP1hero")


def _native_install(root: str) -> None:
    os.makedirs(os.path.join(root, "Data", "data"))
    with open(os.path.join(root, ".build.info"), "w", encoding="utf-8") as handle:
        handle.write("BuildKey\n")
    with open(os.path.join(root, "Data", "data", "data.000"), "wb") as handle:
        handle.write(b"casc")
    with open(
        os.path.join(root, "Data", "data", "0000000000000000.idx"), "wb"
    ) as handle:
        handle.write(b"idx")


def test_native_probe_prefers_casclib_without_path_map(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a native install that CascLib can open without an application path map.
    _native_install(str(tmp_path))
    monkeypatch.setattr(
        "w3xtool.game_data_source.probe_casclib",
        lambda _root: CascLibProbe(
            is_available=True, reason="CascLib storage readable"
        ),
    )

    # When: the install is probed.
    probe = probe_game_data_path(str(tmp_path))

    # Then: the native backend wins and exposes its identity.
    assert probe.backend == "casclib"
    assert probe.is_readable


def test_native_probe_falls_back_to_path_map_with_casclib_reason(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: CascLib cannot load but the legacy path map is present.
    _native_install(str(tmp_path))
    (tmp_path / "w3xray-casc-paths.tsv").write_text("UI/Test.txt\t001122334455667788\n")
    monkeypatch.setattr(
        "w3xtool.game_data_source.probe_casclib",
        lambda _root: CascLibProbe(
            is_available=False, reason="CascLib.dll 架构错误 (193)"
        ),
    )

    # When: the install is probed.
    probe = probe_game_data_path(str(tmp_path))

    # Then: path-map remains readable and the native failure remains visible.
    assert probe.backend == "path_map"
    assert probe.is_readable
    assert "架构错误" in probe.message


def test_native_probe_reports_open_storage_failure_without_fallback(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the DLL loads but CascOpenStorage rejects this installation.
    _native_install(str(tmp_path))
    monkeypatch.setattr(
        "w3xtool.game_data_source.probe_casclib",
        lambda _root: CascLibProbe(
            is_available=False,
            reason="CascOpenStorage 失败，native error=1006",
        ),
    )

    # When: the install is probed.
    probe = probe_game_data_path(str(tmp_path))

    # Then: the precise native reason is shown and no source is opened.
    assert probe.backend is None
    assert not probe.is_readable
    assert "CascOpenStorage" in probe.message
    assert "1006" in probe.message
    assert open_game_data_source(str(tmp_path)) is None


def test_open_native_source_uses_casclib_backend(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a native install and a successful CascLib probe.
    _native_install(str(tmp_path))
    sentinel = DirectoryDataSource.__new__(DirectoryDataSource)
    monkeypatch.setattr(
        "w3xtool.game_data_source.probe_casclib",
        lambda _root: CascLibProbe(is_available=True, reason="readable"),
    )
    monkeypatch.setattr(
        "w3xtool.game_data_source.CascLibDataSource", lambda _root: sentinel
    )

    # When: the unified source factory opens the install.
    source = open_game_data_source(str(tmp_path))

    # Then: it returns the native backend chosen by the probe.
    assert source is sentinel


def test_icon_resolver_closes_game_data_source() -> None:
    # Given: an icon resolver owns a closeable game-data source.
    class ClosableSource:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    source = ClosableSource()
    with tempfile.NamedTemporaryFile(suffix=".w3x") as map_file:
        with patch("w3xtool.icons._open_game_data_source", return_value=source):
            resolver = IconResolver(map_file.name, game_data_path="C:/Warcraft III")

        # When: the resolver lifecycle ends.
        resolver.close()

    # Then: a CascLib-backed storage would be released too.
    assert source.closed


if __name__ == "__main__":
    unittest.main()
