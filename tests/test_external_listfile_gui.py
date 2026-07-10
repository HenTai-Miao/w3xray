"""External listfile file and GUI wiring tests."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from tests.gui_base import GuiTestCase
from w3xtool.api import MapData, _export_all_impl
from w3xtool.archive_source import BytesArchiveSource
from w3xtool.external_listfile import read_external_listfile


class ExternalListfileCoreTest(unittest.TestCase):
    def test_read_external_listfile_normalizes_lines_and_ignores_comments(self) -> None:
        # Given: a user-provided listfile copied from an MPQ tool.
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            handle.write("# comment\n// comment\n//comment\nwar3mapImported\\Hero.mdx\r\nWar3Map.J\n")
            path = handle.name

        try:
            # When: the file is read for archive enumeration.
            names = read_external_listfile(path)

            # Then: only usable archive paths are returned in order.
            self.assertEqual(names, ("war3mapImported\\Hero.mdx", "War3Map.J"))
        finally:
            os.remove(path)

    def test_export_all_impl_uses_external_names_and_keeps_path_safety(self) -> None:
        # Given: an archive has files whose names are absent from its internal listfile.
        class Archive:
            block_table = []
            hash_table = []

            def list_files(self) -> list[str]:
                return []

            def has_file(self, name: str) -> bool:
                return name in {"war3mapImported\\Hero.mdx", "..\\escape.blp"}

            def read_file(self, name: str) -> bytes:
                if name == "war3mapImported\\Hero.mdx":
                    return b"MDX"
                if name == "..\\escape.blp":
                    return b"BAD"
                raise KeyError(name)

            def block_index_of(self, _name: str) -> int | None:
                return None

            def iter_blocks(self):
                return iter(())

            def read_block_anon(self, _block) -> bytes | None:
                return None

        # When: external names are supplied to the export path.
        with tempfile.TemporaryDirectory() as out:
            _export_all_impl(
                Archive(),
                out,
                1,
                external_names=("war3mapImported\\Hero.mdx", "..\\escape.blp"),
            )

            # Then: the valid external name is exported, while unsafe paths are refused.
            with open(os.path.join(out, "war3mapImported", "Hero.mdx"), "rb") as handle:
                self.assertEqual(handle.read(), b"MDX")
            self.assertFalse(os.path.exists(os.path.join(out, "escape.blp")))


class ExternalListfileGuiTest(GuiTestCase):
    def test_gui_selector_persists_external_listfile_path(self) -> None:
        # Given: a listfile selected through the GUI.
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            handle.write("war3map.j\n")
            path = handle.name

        try:
            # When: the selector callback runs.
            with patch("w3xtool.gui_lifecycle.filedialog.askopenfilename", return_value=path):
                self.app.on_pick_external_listfile()

            # Then: the app stores it and exposes the active path in the top bar.
            self.assertEqual(self.app.external_listfile_path, path)
            self.assertIn(os.path.basename(path), self.app.external_listfile_label.cget("text"))
        finally:
            os.remove(path)

    def test_gui_selector_reloads_active_source_with_current_game_data(self) -> None:
        # Given: an active map and game-data directory already selected.
        self.app.map_data = MapData(path="map.w3x", name="重载图")
        self.app.game_data_path = "/game-data"
        calls: list[str] = []

        # When: the external listfile changes.
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            handle.write("hidden/config.json\n")
            path = handle.name
        try:
            with patch("w3xtool.gui_lifecycle.filedialog.askopenfilename", return_value=path):
                with patch.object(self.app, "_start_path_load", side_effect=calls.append):
                    self.app.on_pick_external_listfile()
        finally:
            os.remove(path)

        # Then: the original map is reparsed and the game-data selection is retained.
        self.assertEqual(calls, ["map.w3x"])
        self.assertEqual(self.app.game_data_path, "/game-data")

    def test_gui_clear_listfile_reloads_active_source(self) -> None:
        # Given: an active map currently using an external listfile.
        self.app.map_data = MapData(path="map.w3x", name="清除图")
        self.app.external_listfile_path = "/tmp/names.txt"
        self.app._refresh_external_source_labels()
        calls: list[str] = []

        # When: the listfile selection is cleared.
        with patch.object(self.app, "_start_path_load", side_effect=calls.append):
            self.app.external_listfile_clear.invoke()

        # Then: the map is rebuilt without stale external names.
        self.assertIsNone(self.app.external_listfile_path)
        self.assertEqual(calls, ["map.w3x"])

    def test_export_all_passes_selected_external_listfile_to_worker(self) -> None:
        # Given: a loaded map and a selected external listfile.
        with tempfile.TemporaryDirectory() as out, tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            delete=False,
        ) as handle:
            handle.write("war3mapImported\\Hero.mdx\n")
            listfile_path = handle.name

            calls: list[tuple[str, str | None]] = []

            def fake_export(path: str, *, external_listfile_path: str | None = None) -> str:
                calls.append((path, external_listfile_path))
                return out

            class InlineThread:
                def __init__(self, target, daemon: bool) -> None:
                    self._target = target

                def start(self) -> None:
                    self._target()

            self.app.map_data = MapData(path="map.w3x", name="导出图")
            self.app._campaign_path = None
            self.app.external_listfile_path = listfile_path

            # When: the user clicks export all.
            with patch("w3xtool.gui_export_actions.export_all_files", side_effect=fake_export):
                with patch("w3xtool.gui_export_actions.messagebox.showinfo"):
                    with patch("w3xtool.gui_export_actions.threading.Thread", InlineThread):
                        self.app.on_export_all()
                    self.pump_events_until(lambda: bool(calls))

            # Then: the worker receives the selected listfile path.
            self.assertEqual(calls, [("map.w3x", listfile_path)])

        os.remove(listfile_path)

    def test_export_all_uses_selected_campaign_child_source(self) -> None:
        # Given: the active campaign view is a child backed by owned archive bytes.
        child = MapData(
            path="Maps\\Chapter1.w3x",
            name="第一章",
            archive_source=BytesArchiveSource("Maps\\Chapter1.w3x", b"child"),
        )
        self.app.map_data = child
        self.app._campaign_path = "campaign.w3n"
        self.addCleanup(setattr, self.app, "_campaign_path", None)
        self.addCleanup(child.close)
        self.app.external_listfile_path = "/tmp/child-listfile.txt"
        source_calls: list[tuple[MapData, str | None]] = []
        path_calls: list[str] = []
        errors: list[str] = []
        completions: list[tuple[str, int, str]] = []

        class InlineThread:
            def __init__(self, target, daemon: bool) -> None:
                self._target = target

            def start(self) -> None:
                self._target()

        # When: the selected view is exported.
        with tempfile.TemporaryDirectory() as out:
            def fake_source_export(
                md: MapData,
                *,
                external_listfile_path: str | None = None,
            ) -> str:
                source_calls.append((md, external_listfile_path))
                return out

            with patch(
                "w3xtool.gui_export_actions.export_loaded_map_files",
                side_effect=fake_source_export,
            ):
                with patch(
                    "w3xtool.gui_export_actions.export_all_files",
                    side_effect=lambda path, **_kwargs: path_calls.append(path) or out,
                ):
                    with patch.object(
                        self.app,
                        "_open_dir",
                        side_effect=lambda path, count, kind: completions.append(
                            (path, count, kind)
                        ),
                    ):
                        with patch(
                            "w3xtool.gui_export_actions.messagebox.showerror",
                            side_effect=lambda _title, message: errors.append(message),
                        ):
                            with patch("w3xtool.gui_export_actions.threading.Thread", InlineThread):
                                self.app.on_export_all()
                            self.pump_events_until(
                                lambda: bool(completions) or bool(errors),
                            )

        # Then: the child source and listfile reach the worker; the parent path is unused.
        self.assertEqual(source_calls, [(child, "/tmp/child-listfile.txt")])
        self.assertEqual(path_calls, [])
        self.assertEqual(errors, [])
        self.assertEqual(completions, [(out, 0, "文件")])

    def test_gui_selector_persists_game_data_directory(self) -> None:
        # Given: a Reforged data directory selected through the GUI.
        with tempfile.TemporaryDirectory() as data_dir:
            with patch("w3xtool.gui_lifecycle.filedialog.askdirectory", return_value=data_dir):
                self.app.on_pick_game_data_dir()

            # Then: the app stores it and shows the directory basename in the top bar.
            self.assertEqual(self.app.game_data_path, data_dir)
            self.assertIn(os.path.basename(data_dir), self.app.game_data_label.cget("text"))


if __name__ == "__main__":
    unittest.main()
