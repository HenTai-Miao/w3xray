"""Refresh or clear GUI modules according to load options."""

from __future__ import annotations

from .load_options import (
    COMMANDS_KEY,
    MAP_INFO_KEY,
    OBJECT_BROWSER_KEY,
    ORPHANS_KEY,
    PREPLACED_KEY,
    RECIPES_KEY,
    REPORTS_KEY,
)
from .object_gallery import render_object_gallery
from .theme import PARALLEL_CATS

DISABLED_TEXT = "当前模块已关闭。"


class ModuleRefreshMixin:
    """Apply per-module load options to visible GUI surfaces."""

    def _reset_detail_panel(self) -> None:
        self.detail_title.configure(text="选择对象查看详情")
        self.detail_sub.configure(text="")
        if hasattr(self, "detail_icon"):
            self.detail_icon_image = self.detail_blank_icon
            self.detail_icon.configure(image=self.detail_icon_image, text="")
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.configure(state="disabled")

    def _refresh_enabled_modules(self, cmds, recipes) -> None:
        if self._load_option_enabled(OBJECT_BROWSER_KEY):
            self._refresh_list()
        else:
            self._clear_object_browser()

        self.commands = cmds if self._load_option_enabled(COMMANDS_KEY) else []
        self._refresh_cmds() if self._load_option_enabled(
            COMMANDS_KEY
        ) else self._clear_commands()

        self.recipes = (recipes or []) if self._load_option_enabled(RECIPES_KEY) else []
        self._refresh_recipes() if self._load_option_enabled(
            RECIPES_KEY
        ) else self._clear_recipes()

        self._refresh_preplaced() if self._load_option_enabled(
            PREPLACED_KEY
        ) else self._clear_preplaced()
        self._refresh_orphans() if self._load_option_enabled(
            ORPHANS_KEY
        ) else self._clear_orphans()
        self._refresh_info() if self._load_option_enabled(
            MAP_INFO_KEY
        ) else self._clear_info()
        self._refresh_editor_reports() if self._load_option_enabled(
            REPORTS_KEY
        ) else self._clear_reports()
        self._refresh_item_relations()
        self._set_batch_icon_gaps(None)

    def _clear_object_browser(self) -> None:
        for cat in PARALLEL_CATS:
            self.col_results[cat] = []
            self.col_trees[cat].delete(*self.col_trees[cat].get_children())
            self.col_headers[cat].configure(text=f"{cat}  (0)")
        render_object_gallery(
            self.object_gallery,
            self.active_object_category,
            self.col_results,
            self._show_detail,
        )
        self.object_gallery.hint.configure(text=DISABLED_TEXT)

    def _clear_commands(self) -> None:
        self.cmd_tree.delete(*self.cmd_tree.get_children())
        self.cmd_hint.configure(text=DISABLED_TEXT)

    def _clear_recipes(self) -> None:
        self.rec_tree.delete(*self.rec_tree.get_children())
        self.rec_hint.configure(text=DISABLED_TEXT)

    def _clear_preplaced(self) -> None:
        self.unit_tree.delete(*self.unit_tree.get_children())
        self.doodad_tree.delete(*self.doodad_tree.get_children())
        self.unit_title.configure(text="预放置单位  (0)")
        self.doodad_title.configure(text="装饰物 / 可破坏物  (0)")
        self.pre_hint.configure(text=DISABLED_TEXT)

    def _clear_orphans(self) -> None:
        self.orphan_tree.delete(*self.orphan_tree.get_children())
        self.orphan_hint.configure(text=DISABLED_TEXT)

    def _clear_info(self) -> None:
        self.info_box.configure(state="normal")
        self.info_box.delete("1.0", "end")
        self.info_box.insert("end", DISABLED_TEXT)
        self.info_box.configure(state="disabled")

    def _clear_reports(self) -> None:
        self._set_textbox(self.overview_box, DISABLED_TEXT)
        self._set_textbox(self.analysis_box, DISABLED_TEXT)
        self._render_empty_report(
            self.overview_surface, self.overview_cards, DISABLED_TEXT
        )
        self._render_empty_report(
            self.analysis_surface, self.analysis_cards, DISABLED_TEXT
        )
