"""Main GUI shell layout for the map inspection workbench."""
# pyright: reportAttributeAccessIssue=false, reportUninitializedInstanceVariable=false

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import customtkinter as ctk

from .gui_shell_object_panel import build_object_tab
from .gui_shell_source_panel import build_source_panel
from .gui_topbar import build_topbar
from .theme import (
    ACCENT_DARK,
    ACCENT_HOVER,
    BG,
    BORDER,
    CARD,
    CARD_RAISED,
    FONT,
    HEADER,
    PANEL,
    SECONDARY,
    SEL_BG,
    SEL_TEXT,
    SUBTLE,
    TEXT,
    TEXT_STRONG,
    TOPBAR,
)


class ShellLayoutMixin:
    """Build the always-visible source rail and editor workspace."""

    detail_title: ctk.CTkLabel

    def _build_topbar(self) -> None:
        build_topbar(self)

    def _build_tabs(self) -> None:
        shell = ctk.CTkFrame(self, fg_color=BG)
        shell.pack(fill="both", expand=True, padx=12, pady=(10, 8))
        self.source_panel = ctk.CTkFrame(
            shell,
            width=286,
            fg_color=TOPBAR,
            corner_radius=18,
            border_width=1,
            border_color=BORDER,
        )
        self.source_panel.pack(side="left", fill="y", padx=(0, 10))
        self.source_panel.pack_propagate(False)
        self._build_source_panel(self.source_panel)
        content = ctk.CTkFrame(shell, fg_color=BG)
        content.pack(side="left", fill="both", expand=True)
        self.tabs = ctk.CTkTabview(
            content,
            fg_color=BG,
            segmented_button_selected_color=ACCENT_DARK,
            segmented_button_selected_hover_color=ACCENT_HOVER,
            segmented_button_unselected_color=CARD,
            segmented_button_unselected_hover_color=CARD_RAISED,
            text_color=TEXT,
        )
        self.tabs.pack(fill="both", expand=True)
        self.editor_tab_labels = (
            "总览",
            "对象编辑器",
            "地图信息",
            "GUI触发器",
            "场景放置",
            "掉落/获取",
            "触发指令",
            "合成配方",
            "孤立对象",
            "分析报告",
            "图标缺口",
            "批量状态",
        )
        self.tab_overview = self.tabs.add("总览")
        self.tab_obj = self.tabs.add("对象编辑器")
        self.tab_info = self.tabs.add("地图信息")
        self.tab_trigger_eca = self.tabs.add("GUI触发器")
        self.tab_pre = self.tabs.add("场景放置")
        self.tab_item_relations = self.tabs.add("掉落/获取")
        self.tab_cmd = self.tabs.add("触发指令")
        self.tab_rec = self.tabs.add("合成配方")
        self.tab_orphan = self.tabs.add("孤立对象")
        self.tab_analysis = self.tabs.add("分析报告")
        self.tab_icon_gaps = self.tabs.add("图标缺口")
        self.tab_batch_status = self.tabs.add("批量状态")
        self._build_overview_tab(self.tab_overview)
        self._build_obj_tab(self.tab_obj)
        self._build_info_tab(self.tab_info)
        self._build_trigger_eca_tab(self.tab_trigger_eca)
        self._build_preplaced_tab(self.tab_pre)
        self._build_item_relation_tab(self.tab_item_relations)
        self._build_cmd_tab(self.tab_cmd)
        self._build_rec_tab(self.tab_rec)
        self._build_orphan_tab(self.tab_orphan)
        self._build_analysis_tab(self.tab_analysis)
        self._build_icon_gap_tab(self.tab_icon_gaps)
        self._build_batch_status_tab(self.tab_batch_status)
        self._refresh_editor_reports()

    def _build_source_panel(self, parent) -> None:
        build_source_panel(self, parent)

    def _build_obj_tab(self, parent) -> None:
        build_object_tab(self, parent)

    def _build_detail_panel(self, paned) -> None:
        from .gui_shell_object_panel import build_detail_panel

        build_detail_panel(self, paned)

    def _build_statusbar(self) -> None:
        bar = ctk.CTkFrame(
            self,
            fg_color=TOPBAR,
            corner_radius=0,
            height=32,
            border_width=1,
            border_color=BORDER,
        )
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)
        self.status = ctk.CTkLabel(
            bar,
            text="就绪 · 点击「打开地图」开始",
            anchor="w",
            font=(FONT, 12),
            text_color=SUBTLE,
        )
        self.status.pack(fill="both", expand=True, padx=16)

    def _setup_tree_style(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            style = ttk.Style()
        style.configure(
            "Treeview",
            background=CARD,
            fieldbackground=CARD,
            foreground=TEXT,
            rowheight=31,
            borderwidth=0,
            relief="flat",
            font=(FONT, 11),
        )
        style.configure(
            "Treeview.Heading",
            background=HEADER,
            foreground=TEXT_STRONG,
            font=(FONT, 11, "bold"),
            borderwidth=0,
            relief="flat",
        )
        style.map(
            "Treeview",
            background=[("selected", SEL_BG)],
            foreground=[("selected", SEL_TEXT)],
        )
        style.map("Treeview.Heading", background=[("active", CARD_RAISED)])
        style.configure(
            "Vertical.TScrollbar",
            background=SECONDARY,
            troughcolor=PANEL,
            borderwidth=0,
            arrowsize=11,
        )
        style.configure(
            "Horizontal.TScrollbar",
            background=SECONDARY,
            troughcolor=PANEL,
            borderwidth=0,
            arrowsize=11,
        )
