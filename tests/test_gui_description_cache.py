"""Trusted-description cache selection and persistence tests."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import tkinter as tk
from unittest.mock import patch

from tests.gui_base import GuiTestCase
from w3xtool.gui import App
from w3xtool.description_cache import (
    DescriptionCache,
    DescriptionCacheEntry,
    format_description_cache_tsv,
)


class DescriptionCacheGuiTest(GuiTestCase):
    def test_valid_cache_selection_persists_and_reloads_active_source(self) -> None:
        # Given: a valid standalone cache and an isolated GUI config path.
        tmp_path = Path(self.enterContext(TemporaryDirectory()))
        cache_path = _write_cache(tmp_path / "trusted.tsv")
        config_path = tmp_path / "gui.json"

        # When: the user selects the trusted cache.
        with (
            patch(
                "w3xtool.gui_external_data.filedialog.askopenfilename",
                return_value=str(cache_path),
            ),
            patch.object(self.app, "_config_path", return_value=str(config_path)),
            patch.object(self.app, "_reload_active_source") as reload_source,
        ):
            self.app.on_pick_description_cache()

        # Then: the path is active, persisted, and applied through a reload.
        assert self.app.description_cache_path == str(cache_path)
        assert json.loads(config_path.read_text(encoding="utf-8"))[
            "description_cache_path"
        ] == str(cache_path)
        reload_source.assert_called_once_with()
        assert _cache_menu_state(self.app) == "normal"

    def test_invalid_cache_schema_is_rejected(self) -> None:
        # Given: a regular TSV file that is not a tool-generated cache.
        tmp_path = Path(self.enterContext(TemporaryDirectory()))
        invalid = tmp_path / "invalid.tsv"
        invalid.write_text("错误\t表头\n", encoding="utf-8")

        # When: the user attempts to select it.
        with (
            patch(
                "w3xtool.gui_external_data.filedialog.askopenfilename",
                return_value=str(invalid),
            ),
            patch("w3xtool.gui_external_data.messagebox.showerror") as show_error,
        ):
            self.app.on_pick_description_cache()

        # Then: the invalid path is not activated and an explicit error is shown.
        assert self.app.description_cache_path is None
        show_error.assert_called_once()

    def test_symlink_cache_is_rejected(self) -> None:
        # Given: a symlink points at an otherwise valid cache file.
        tmp_path = Path(self.enterContext(TemporaryDirectory()))
        target = _write_cache(tmp_path / "trusted.tsv")
        link = tmp_path / "linked.tsv"
        link.symlink_to(target)

        # When: the symlink is selected.
        with (
            patch(
                "w3xtool.gui_external_data.filedialog.askopenfilename",
                return_value=str(link),
            ),
            patch("w3xtool.gui_external_data.messagebox.showerror") as show_error,
        ):
            self.app.on_pick_description_cache()

        # Then: it cannot become trusted input.
        assert self.app.description_cache_path is None
        show_error.assert_called_once()

    def test_clear_cache_persists_none_and_reloads(self) -> None:
        # Given: a previously selected trusted cache.
        tmp_path = Path(self.enterContext(TemporaryDirectory()))
        config_path = tmp_path / "gui.json"
        self.app.description_cache_path = str(_write_cache(tmp_path / "trusted.tsv"))

        # When: the user clears it.
        with (
            patch.object(self.app, "_config_path", return_value=str(config_path)),
            patch.object(self.app, "_reload_active_source") as reload_source,
        ):
            self.app.on_clear_description_cache()

        # Then: state, persistence, menu state, and loaded evidence are refreshed.
        assert self.app.description_cache_path is None
        assert (
            json.loads(config_path.read_text(encoding="utf-8"))[
                "description_cache_path"
            ]
            is None
        )
        reload_source.assert_called_once_with()
        assert _cache_menu_state(self.app) == "disabled"

    def test_restore_accepts_only_a_valid_regular_cache(self) -> None:
        # Given: persisted configuration points at a valid trusted cache.
        tmp_path = Path(self.enterContext(TemporaryDirectory()))
        cache_path = _write_cache(tmp_path / "trusted.tsv")
        config_path = tmp_path / "gui.json"
        config_path.write_text(
            json.dumps({"description_cache_path": str(cache_path)}),
            encoding="utf-8",
        )

        # When: cache state is restored at startup.
        with patch.object(self.app, "_config_path", return_value=str(config_path)):
            self.app._restore_description_cache()

        # Then: the validated path becomes the active load input.
        assert self.app.description_cache_path == str(cache_path)


def _write_cache(path: Path) -> Path:
    entry = DescriptionCacheEntry(
        category="物品",
        base_id="ratf",
        role="扩展说明",
        level=None,
        raw_value="原始说明",
        readable_value="可读说明",
        source_map_sha256="a" * 64,
        source_manifest_sha256="b" * 64,
        source_path="对象完整描述.tsv",
    )
    path.write_text(
        format_description_cache_tsv(DescriptionCache.build((entry,))),
        encoding="utf-8",
    )
    return path


def _cache_menu_state(app: App) -> str:
    menu = app.__dict__.get("data_tools_menu")
    assert isinstance(menu, tk.Menu)
    return str(menu.entrycget("清除可信描述缓存", "state"))
