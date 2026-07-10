"""GUI entrypoint state for native CASC browsing."""

from __future__ import annotations

from unittest.mock import patch

from tests.gui_base import GuiTestCase
from w3xtool.casclib_enumeration import CascEntry, CascNameType
from w3xtool.game_data_inventory import GameDataInventoryView
from w3xtool.game_data_source import GameDataProbe


class _InventorySource:
    inventory_view = GameDataInventoryView.KNOWN_PATHS

    def __init__(self) -> None:
        self.closed = False

    def has_file(self, _name: str) -> bool:
        return True

    def read_file(self, _name: str) -> bytes:
        return b"data"

    def iter_entries(self, _mask: str = "*", _listfile: str | None = None):
        yield CascEntry("UI\\Test.txt", CascNameType.FULL, None, "", "", 4, True, None, None)

    def close(self) -> None:
        self.closed = True


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
        source = _InventorySource()
        source.inventory_view = GameDataInventoryView.FULL_ROOT

        # When: source controls refresh after selection.
        with patch("w3xtool.gui_lifecycle.probe_game_data_path", return_value=probe):
            with patch("w3xtool.gui_lifecycle.open_game_data_source", return_value=source):
                self.app._refresh_external_source_labels()

        # Then: the full-root browser command is available.
        self.assertEqual(self.app.data_tools_menu.entrycget("浏览 CASC Root", "state"), "normal")
        self.assertTrue(source.closed)

    def test_browser_is_enabled_for_readable_inventory_fallback(self) -> None:
        # Given: a readable extracted directory exposes a known-path inventory.
        self.app.game_data_path = "/game-data"
        probe = GameDataProbe("extracted_dir", True, "ok", "directory")
        source = _InventorySource()

        # When: source controls refresh after selection.
        with patch("w3xtool.gui_lifecycle.probe_game_data_path", return_value=probe):
            with patch("w3xtool.gui_lifecycle.open_game_data_source", return_value=source, create=True):
                self.app._refresh_external_source_labels()

        # Then: capability, not native backend identity, enables browsing.
        self.assertEqual(self.app.data_tools_menu.entrycget("浏览 CASC Root", "state"), "normal")
        self.assertTrue(source.closed)

    def test_browser_action_opens_source_through_common_factory(self) -> None:
        # Given: the selected game data is a fallback inventory source.
        self.app.game_data_path = "/game-data"
        source = _InventorySource()
        shown: list[_InventorySource] = []

        class InlineThread:
            def __init__(self, target, daemon: bool) -> None:
                self._target = target

            def start(self) -> None:
                self._target()

        # When: the browser action opens in its worker.
        with patch(
            "w3xtool.gui_casc_browser.open_game_data_source",
            return_value=source,
            create=True,
        ):
            with patch(
                "w3xtool.gui_casc_browser.CascLibDataSource",
                side_effect=AssertionError("native constructor bypass"),
                create=True,
            ):
                with patch("w3xtool.gui_casc_browser.threading.Thread", InlineThread):
                    with patch.object(self.app, "_show_casc_browser", side_effect=shown.append):
                        self.app.on_browse_game_data()
                        self.pump_events_until(lambda: bool(shown))

        # Then: the common source reaches the browser unchanged.
        self.assertEqual(shown, [source])
