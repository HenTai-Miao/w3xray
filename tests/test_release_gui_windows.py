"""Real Tk regression for closing the guide content window."""

from __future__ import annotations

from unittest.mock import patch

import customtkinter as ctk

from gametool.gui_live_probe import LiveProbeWindow
from gametool.gui_profile_settings import ExtractionProfileDialog
from gametool.gui_topbar import _GUIDE_SCROLL, _open_guide_window
from gametool.map_data import MapData
from tests.gui_base import GuiTestCase


class GuideWindowCloseTest(GuiTestCase):
    def test_guide_close_remembers_its_source_before_text_is_destroyed(self) -> None:
        self.app.map_data = MapData(path="guide-source.w3x", name="攻略来源")
        errors: list[str] = []
        existing = set(self.app.winfo_children())
        with patch.object(
            self.app,
            "report_callback_exception",
            side_effect=lambda _kind, error, _trace: errors.append(str(error)),
        ):
            _open_guide_window(self.app, "【基本信息】\n当前地图的完整攻略\n")
            window = next(
                child
                for child in self.app.winfo_children()
                if child not in existing and isinstance(child, ctk.CTkToplevel)
            )
            self.app.update_idletasks()
            self.app.update()
            self.app.map_data = MapData(path="next-map.w3x", name="之后打开的地图")

            window.destroy()
            self.app.update()

        assert errors == []
        assert "guide-source.w3x" in _GUIDE_SCROLL
        assert "next-map.w3x" not in _GUIDE_SCROLL


class ToolbarDialogCallbackTest(GuiTestCase):
    def test_profile_settings_button_opens_dialog_with_app_as_master(self) -> None:
        existing = set(self.app.winfo_children())
        self.app.profile_settings_button.invoke()  # pyright: ignore[reportAttributeAccessIssue] - topbar injects the button.
        dialog = next(
            child
            for child in self.app.winfo_children()
            if child not in existing and isinstance(child, ExtractionProfileDialog)
        )
        try:
            self.app.update_idletasks()
            self.app.update()
            assert dialog.master is self.app
            assert dialog.winfo_exists()
        finally:
            dialog.destroy()

    def test_neighboring_host_callbacks_open_live_and_hotkey_dialogs(self) -> None:
        errors: list[str] = []
        with (
            patch.object(LiveProbeWindow, "_start", return_value=None),
            patch.object(
                self.app,
                "report_callback_exception",
                side_effect=lambda _kind, error, _trace: errors.append(str(error)),
            ),
        ):
            existing = set(self.app.winfo_children())
            self.app.live_probe_button.invoke()  # pyright: ignore[reportAttributeAccessIssue] - topbar injects the button.
            live = next(
                child
                for child in self.app.winfo_children()
                if child not in existing and isinstance(child, LiveProbeWindow)
            )
            self.app.update_idletasks()
            self.app.update()
            assert live.master is self.app
            live.destroy()

            existing = set(self.app.winfo_children())
            self.app.data_tools_menu.invoke("键盘速查")
            hotkeys = next(
                child
                for child in self.app.winfo_children()
                if child not in existing and isinstance(child, ctk.CTkToplevel)
            )
            self.app.update_idletasks()
            self.app.update()
            assert hotkeys.master is self.app
            hotkeys.destroy()
            self.app.update()

        assert errors == []
