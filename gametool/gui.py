"""GameXRay 游戏档案透视器 GUI（CustomTkinter 工作台）。"""

from __future__ import annotations

import tkinter as tk

import customtkinter as ctk
from PIL import Image

from typing import TYPE_CHECKING

from .api import MapData

if TYPE_CHECKING:
    from .gui_icon_cache import _IconResolverLike
    from .script_scan import ChatCommand, Recipe

from .gui_clipboard import ClipboardMixin
from .gui_current_map import CurrentMapGuiMixin
from .gui_casc_browser import CascBrowserMixin
from .gui_data_refresh import DataRefreshMixin
from .gui_data_tabs import DataTabLayoutMixin
from .gui_export_actions import ExportActionsMixin
from .gui_external_data import ExternalDataToolsMixin
from .gui_icon_cache import IconCacheMixin
from .gui_icon_gaps import IconGapGuiMixin
from .gui_item_relations import ItemRelationGuiMixin
from .gui_batch_status import BatchStatusGuiMixin
from .gui_lifecycle import GuiLifecycleMixin
from .gui_load_settings import LoadSettingsMixin
from .gui_loader_runner import BackgroundLoaderMixin
from .gui_module_refresh import ModuleRefreshMixin
from .gui_object_detail import ObjectDetailMixin
from .gui_object_text_controls import ObjectTextControlsMixin
from .gui_object_filter_runner import ObjectFilterRunnerMixin
from .gui_pane_state import PaneStateMixin
from .gui_report_tabs import ReportTabsMixin
from .gui_shell import ShellLayoutMixin
from .gui_source_browser import SourceBrowserMixin
from .gui_trigger_eca import TriggerEcaViewMixin
from .gui_worker_host import GuiWorkerHostMixin
from .theme import BG

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("green")


class App(
    GuiWorkerHostMixin,
    CascBrowserMixin,
    ExternalDataToolsMixin,
    BatchStatusGuiMixin,
    IconGapGuiMixin,
    ItemRelationGuiMixin,
    LoadSettingsMixin,
    IconCacheMixin,
    ModuleRefreshMixin,
    ObjectFilterRunnerMixin,
    PaneStateMixin,
    BackgroundLoaderMixin,
    ReportTabsMixin,
    ExportActionsMixin,
    TriggerEcaViewMixin,
    ShellLayoutMixin,
    DataTabLayoutMixin,
    DataRefreshMixin,
    SourceBrowserMixin,
    ObjectDetailMixin,
    ObjectTextControlsMixin,
    CurrentMapGuiMixin,
    GuiLifecycleMixin,
    ClipboardMixin,
    ctk.CTk,
):
    """Compose the GUI from focused mixins."""

    # 宿主注入字段的权威类型 (压过各 mixin 的 TYPE_CHECKING 声明, 消解多基类 MRO 合并冲突)
    map_data: MapData | None
    commands: list[ChatCommand]
    recipes: list[Recipe]
    icons: _IconResolverLike | None
    external_listfile_path: str | None
    game_data_path: str | None
    author_bundle_path: str | None
    description_cache_path: str | None
    mode: str
    _campaign_views: object | None
    _campaign_path: str | None
    _cur_dir: dict[str, str | None]
    _pil_icon_cache: dict[tuple[str, int], Image.Image | None]
    _photo_cache: dict[tuple[str, int, str], object]

    def __init__(self) -> None:
        super().__init__()
        self._init_gui_worker_host()
        self._init_icon_gap_gui()
        self._init_batch_status_gui()
        self.title("GameXRay 游戏档案透视器")
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
        self.author_bundle_path = None
        self.description_cache_path = None
        self.description_cache_manifest_sha256 = ""
        self.description_cache_entry_count = 0
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
        self._casc_browser_dialog = None

        self._init_current_map_gui()
        self._init_load_options()
        self._init_background_loader()
        self._init_object_filter_runner()
        self._init_pane_state()
        self._build_topbar()
        self._restore_external_sources()
        self._restore_description_cache()
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
            return

    def destroy(self) -> None:
        """Retire this app's Tcl timers before its widget commands disappear."""
        from .gui_tk_callbacks import cancel_widget_callbacks

        cancel_widget_callbacks(self)
        super().destroy()


def main() -> None:
    App().mainloop()


if __name__ == "__main__":
    main()
