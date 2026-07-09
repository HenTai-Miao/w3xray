"""魔兽地图提取器 GUI（CustomTkinter 工作台）。"""

from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from .api import MapData
from .gui_clipboard import ClipboardMixin
from .gui_data_refresh import DataRefreshMixin
from .gui_data_tabs import DataTabLayoutMixin
from .gui_export_actions import ExportActionsMixin
from .gui_icon_cache import IconCacheMixin
from .gui_lifecycle import GuiLifecycleMixin
from .gui_load_settings import LoadSettingsMixin
from .gui_loader_runner import BackgroundLoaderMixin
from .gui_module_refresh import ModuleRefreshMixin
from .gui_object_detail import ObjectDetailMixin
from .gui_object_filter_runner import ObjectFilterRunnerMixin
from .gui_pane_state import PaneStateMixin
from .gui_report_tabs import ReportTabsMixin
from .gui_shell import ShellLayoutMixin
from .gui_source_browser import SourceBrowserMixin
from .theme import BG

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("green")


class App(
    LoadSettingsMixin,
    IconCacheMixin,
    ModuleRefreshMixin,
    ObjectFilterRunnerMixin,
    PaneStateMixin,
    BackgroundLoaderMixin,
    ReportTabsMixin,
    ExportActionsMixin,
    ShellLayoutMixin,
    DataTabLayoutMixin,
    DataRefreshMixin,
    SourceBrowserMixin,
    ObjectDetailMixin,
    GuiLifecycleMixin,
    ClipboardMixin,
    ctk.CTk,
):
    """Compose the GUI from focused mixins."""

    def __init__(self) -> None:
        super().__init__()
        self.title("W3XRAY 魔兽地图提取器")
        self.geometry("1440x860")
        self.minsize(1040, 640)
        self.configure(fg_color=BG)

        self.map_data: MapData | None = None
        self.current_category = "全部"
        self.results = []
        self.commands = []
        self.recipes = []
        self.icons = None
        self.external_listfile_path = None
        self.game_data_path = None
        self.mode = "battle"
        self._campaign_views = None
        self._campaign_path = None
        self._dir_campaigns = []
        self._node_map = {}
        self._cur_dir = {"battle": None, "campaign": None}
        self._pil_icon_cache = {}
        self._photo_cache = {}
        self._row_imgs = []
        self._blank = None

        self._init_load_options()
        self._init_background_loader()
        self._init_object_filter_runner()
        self._init_pane_state()
        self._build_topbar()
        self._restore_external_sources()
        self._build_tabs()
        self._build_statusbar()
        self._setup_tree_style()
        self._restore_window_geometry()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(300, self._restore_last_dir)
        self.after(500, self._restore_pane_sashes)

    def _restore_window_geometry(self) -> None:
        geometry = self._load_config().get("geometry")
        if not geometry:
            return
        try:
            self.geometry(geometry)
        except tk.TclError:
            pass


def main() -> None:
    App().mainloop()


if __name__ == "__main__":
    main()
