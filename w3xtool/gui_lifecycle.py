"""Application lifecycle, config, and map render handoff."""

from __future__ import annotations

import json
import logging
import os
from tkinter import filedialog

from .game_data_inventory import supports_inventory
from .game_data_source import open_game_data_source, probe_game_data_path

_LOGGER = logging.getLogger(__name__)


class GuiLifecycleMixin:
    """Own app-level config, open-file action, and shutdown flow."""

    def _config_path(self) -> str:
        return os.path.join(os.path.expanduser("~"), ".w3x_extractor.json")

    def _save_config(self, **values) -> None:
        cfg = {}
        try:
            with open(self._config_path(), "r", encoding="utf-8") as file:
                cfg = json.load(file)
        except (OSError, json.JSONDecodeError):
            cfg = {}
        cfg.update(values)
        try:
            with open(self._config_path(), "w", encoding="utf-8") as file:
                json.dump(cfg, file, ensure_ascii=False)
        except OSError:
            _LOGGER.debug("failed to save GUI configuration", exc_info=True)

    def _load_config(self):
        try:
            with open(self._config_path(), "r", encoding="utf-8") as file:
                return json.load(file)
        except (OSError, json.JSONDecodeError):
            return {}

    def _restore_last_dir(self) -> None:
        cfg = self._load_config()
        battle_dir = cfg.get("last_dir_battle") or cfg.get("last_dir")
        campaign_dir = cfg.get("last_dir_campaign")
        if battle_dir and os.path.isdir(battle_dir):
            self._cur_dir["battle"] = battle_dir
            self._scan_dir(battle_dir, "battle")
        if campaign_dir and os.path.isdir(campaign_dir):
            self._cur_dir["campaign"] = campaign_dir
            self._scan_dir(campaign_dir, "campaign")

    def _restore_external_sources(self) -> None:
        cfg = self._load_config()
        listfile = cfg.get("external_listfile_path")
        game_data = cfg.get("game_data_path")
        author_bundle = cfg.get("author_bundle_path")
        if listfile and os.path.isfile(listfile):
            self.external_listfile_path = listfile
        if game_data and os.path.isdir(game_data):
            self.game_data_path = game_data
        if author_bundle and os.path.isfile(os.path.join(author_bundle, "w3xray-author-bundle.tsv")):
            self.author_bundle_path = author_bundle
        self._refresh_external_source_labels()

    def on_pick_external_listfile(self) -> None:
        path = filedialog.askopenfilename(
            title="选择外部 listfile",
            filetypes=[("MPQ listfile", "*.txt *.lst *.listfile"), ("所有文件", "*.*")],
        )
        if not path:
            return
        self.external_listfile_path = path
        self._save_config(external_listfile_path=path)
        self._refresh_external_source_labels()
        self._reload_active_source()

    def on_clear_external_listfile(self) -> None:
        self.external_listfile_path = None
        self._save_config(external_listfile_path=None)
        self._refresh_external_source_labels()
        self._reload_active_source()

    def on_pick_game_data_dir(self) -> None:
        path = filedialog.askdirectory(title="选择已导出的魔兽重制版数据目录")
        if not path:
            return
        self.game_data_path = path
        self._save_config(game_data_path=path)
        self._refresh_external_source_labels()
        self._reload_active_source()

    def _reload_active_source(self) -> None:
        if self.map_data is None:
            return
        self._start_path_load(self._campaign_path or self.map_data.path)

    def _refresh_external_source_labels(self) -> None:
        if hasattr(self, "external_listfile_label"):
            self.external_listfile_label.configure(text=_source_label("listfile", self.external_listfile_path))
        if hasattr(self, "external_listfile_clear"):
            self.external_listfile_clear.configure(
                state="normal" if self.external_listfile_path else "disabled",
            )
        browser_state = "disabled"
        if hasattr(self, "game_data_label"):
            label = _source_label("游戏数据", self.game_data_path)
            if self.game_data_path:
                probe = probe_game_data_path(self.game_data_path)
                if not probe.is_readable:
                    label = f"游戏数据: {os.path.basename(self.game_data_path)} 需导出"
                else:
                    source = open_game_data_source(self.game_data_path)
                    try:
                        if supports_inventory(source):
                            browser_state = "normal"
                    finally:
                        if source is not None:
                            source.close()
            self.game_data_label.configure(text=label)
        if hasattr(self, "data_tools_menu"):
            self.data_tools_menu.entryconfigure("浏览 CASC Root", state=browser_state)
            clear_state = "normal" if self.author_bundle_path else "disabled"
            self.data_tools_menu.entryconfigure("清除作者明文补充包", state=clear_state)
        if hasattr(self, "data_tools_button"):
            self.data_tools_button.configure(text="数据工具*" if self.author_bundle_path else "数据工具")

    def _on_close(self) -> None:
        dialog = getattr(self, "_casc_browser_dialog", None)
        if dialog is not None and dialog.winfo_exists():
            dialog.close()
        self._shutdown_background_loader()
        self._shutdown_object_filter_runner()
        self._save_layout_state(geometry=self.geometry())
        if self.icons is not None and hasattr(self.icons, "close"):
            try:
                self.icons.close()
            except OSError:
                _LOGGER.debug("failed to close icon resolver during shutdown", exc_info=True)
        self._shutdown_current_map_gui()
        self.destroy()

    def on_open(self) -> None:
        path = filedialog.askopenfilename(
            title="选择魔兽地图或战役",
            filetypes=[("魔兽地图/战役", "*.w3x *.w3m *.w3n"), ("所有文件", "*.*")])
        if not path:
            return
        self._start_path_load(path)

    def _on_loaded(self, md, cmds, recipes=None, resolver=None, views=None, campaign_path=None) -> None:
        if views:
            self._set_campaign_views(views, campaign_path)
        else:
            self.mode = "battle"
            self.mode_seg.set("对战图")
            self._campaign_views = None
            self._campaign_path = None
            self._populate_left()
        self._render_map(md, cmds, recipes, resolver)

    def _render_map(self, md, cmds, recipes, resolver) -> None:
        self.map_data = md
        old = self.icons
        if old is not None and old is not resolver and hasattr(old, "close"):
            try:
                old.close()
            except OSError:
                _LOGGER.debug("failed to close replaced icon resolver", exc_info=True)
        self.icons = resolver
        self._pil_icon_cache = {}
        self._photo_cache = {}
        self.map_label.configure(text=f"当前地图：{md.name}")
        self._reset_detail_panel()
        self._refresh_enabled_modules(cmds, recipes)
        self._refresh_trigger_eca()
        counts = md.category_counts()
        total = sum(counts.values())
        self.status.configure(text=f"已加载 {md.name} · {total} 对象 · "
                              f"{len(cmds)} 指令 · "
                              f"{len(self.recipes)} 合成 · "
                              + "  ".join(f"{category}{count}" for category, count in counts.items()))


def _source_label(prefix: str, path: str | None) -> str:
    if not path:
        return f"{prefix}: 未选"
    return f"{prefix}: {os.path.basename(path) or path}"
