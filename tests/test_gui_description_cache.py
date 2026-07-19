"""Owned trusted-description cache selection and persistence tests."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import gettempdir, TemporaryDirectory
import tkinter as tk
from unittest.mock import patch

import customtkinter as ctk

from tests.gui_base import GuiTestCase
from tests.trusted_description_cache_fixture import published_cache
from w3xtool.gui import App
from w3xtool.trusted_description_cache import load_trusted_description_cache

_CANONICAL_TEMP_ROOT = Path(gettempdir()).resolve()


class DescriptionCacheGuiTest(GuiTestCase):
    def test_valid_cache_root_persists_and_shows_verified_identity(self) -> None:
        # Given
        tmp_path = Path(self.enterContext(TemporaryDirectory(dir=_CANONICAL_TEMP_ROOT)))
        cache_root = published_cache(tmp_path / "fixture")
        verified = load_trusted_description_cache(cache_root)
        config_path = tmp_path / "gui.json"

        # When
        with (
            patch(
                "w3xtool.gui_external_data.filedialog.askdirectory",
                return_value=str(cache_root),
            ),
            patch(
                "w3xtool.gui_external_data.filedialog.askopenfilename",
                return_value="",
            ),
            patch.object(self.app, "_config_path", return_value=str(config_path)),
            patch.object(self.app, "_reload_active_source") as reload_source,
        ):
            self.app.on_pick_description_cache()

        # Then
        assert self.app.description_cache_path == str(cache_root)
        assert json.loads(config_path.read_text(encoding="utf-8"))[
            "description_cache_path"
        ] == str(cache_root)
        reload_source.assert_called_once_with()
        label = _cache_button_text(self.app)
        assert verified.manifest_sha256[:12] in label
        assert "1 条" in label
        assert _cache_menu_state(self.app) == "normal"

    def test_invalid_cache_root_keeps_previous_selection(self) -> None:
        # Given
        tmp_path = Path(self.enterContext(TemporaryDirectory(dir=_CANONICAL_TEMP_ROOT)))
        previous = published_cache(tmp_path / "previous")
        invalid = tmp_path / "invalid"
        invalid.mkdir()
        self.app.description_cache_path = str(previous)

        # When
        with (
            patch(
                "w3xtool.gui_external_data.filedialog.askdirectory",
                return_value=str(invalid),
            ),
            patch(
                "w3xtool.gui_external_data.filedialog.askopenfilename",
                return_value="",
            ),
            patch("w3xtool.gui_external_data.messagebox.showerror") as show_error,
            patch.object(self.app, "_save_config") as save_config,
            patch.object(self.app, "_reload_active_source") as reload_source,
        ):
            self.app.on_pick_description_cache()

        # Then
        assert self.app.description_cache_path == str(previous)
        show_error.assert_called_once()
        save_config.assert_not_called()
        reload_source.assert_not_called()

    def test_cancelled_picker_keeps_previous_selection(self) -> None:
        # Given
        tmp_path = Path(self.enterContext(TemporaryDirectory(dir=_CANONICAL_TEMP_ROOT)))
        previous = published_cache(tmp_path / "previous")
        self.app.description_cache_path = str(previous)

        # When
        with (
            patch(
                "w3xtool.gui_external_data.filedialog.askdirectory",
                return_value="",
            ),
            patch(
                "w3xtool.gui_external_data.filedialog.askopenfilename",
                return_value="",
            ),
            patch.object(self.app, "_save_config") as save_config,
        ):
            self.app.on_pick_description_cache()

        # Then
        assert self.app.description_cache_path == str(previous)
        save_config.assert_not_called()

    def test_clear_cache_persists_none_and_reloads(self) -> None:
        # Given
        tmp_path = Path(self.enterContext(TemporaryDirectory(dir=_CANONICAL_TEMP_ROOT)))
        config_path = tmp_path / "gui.json"
        self.app.description_cache_path = str(published_cache(tmp_path / "fixture"))

        # When
        with (
            patch.object(self.app, "_config_path", return_value=str(config_path)),
            patch.object(self.app, "_reload_active_source") as reload_source,
        ):
            self.app.on_clear_description_cache()

        # Then
        assert self.app.description_cache_path is None
        assert (
            json.loads(config_path.read_text(encoding="utf-8"))[
                "description_cache_path"
            ]
            is None
        )
        reload_source.assert_called_once_with()
        assert _cache_menu_state(self.app) == "disabled"

    def test_restore_accepts_only_a_verified_owned_root(self) -> None:
        # Given
        tmp_path = Path(self.enterContext(TemporaryDirectory(dir=_CANONICAL_TEMP_ROOT)))
        cache_root = published_cache(tmp_path / "fixture")
        config_path = tmp_path / "gui.json"
        config_path.write_text(
            json.dumps({"description_cache_path": str(cache_root)}),
            encoding="utf-8",
        )

        # When
        with patch.object(self.app, "_config_path", return_value=str(config_path)):
            self.app._restore_description_cache()

        # Then
        assert self.app.description_cache_path == str(cache_root)


def _cache_menu_state(app: App) -> str:
    menu = app.__dict__.get("data_tools_menu")
    assert isinstance(menu, tk.Menu)
    return str(menu.entrycget("清除可信描述缓存", "state"))


def _cache_button_text(app: App) -> str:
    button = app.__dict__.get("data_tools_button")
    assert isinstance(button, ctk.CTkButton)
    return str(button.cget("text"))
