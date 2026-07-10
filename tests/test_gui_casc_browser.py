"""GUI entrypoint state for native CASC browsing."""

from __future__ import annotations

from unittest.mock import patch

from tests.gui_base import GuiTestCase
from w3xtool.game_data_source import GameDataProbe


class CascBrowserEntryTest(GuiTestCase):
    def test_browser_is_disabled_without_native_casc_source(self) -> None:
        # Given: no selected game data directory.
        self.app.game_data_path = None

        # When: source controls refresh.
        self.app._refresh_external_source_labels()

        # Then: browsing cannot open a non-existent native storage.
        self.assertEqual(self.app.data_tools_menu.entrycget("浏览 CASC Root", "state"), "disabled")

    def test_browser_is_enabled_for_readable_casclib_backend(self) -> None:
        # Given: the selected directory probes as a real CascLib source.
        self.app.game_data_path = "C:/Warcraft III"
        probe = GameDataProbe("native_casc", True, "ok", "casclib")

        # When: source controls refresh after selection.
        with patch("w3xtool.gui_lifecycle.probe_game_data_path", return_value=probe):
            self.app._refresh_external_source_labels()

        # Then: the full-root browser command is available.
        self.assertEqual(self.app.data_tools_menu.entrycget("浏览 CASC Root", "state"), "normal")
