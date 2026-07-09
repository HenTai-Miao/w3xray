"""Main GUI shell layout for the map inspection workbench."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import customtkinter as ctk
from PIL import Image

from .deferred_paned import add_deferred_pane, build_deferred_horizontal_paned
from .gui_pane_state import OBJECT_EDITOR_PANE_KEY
from .gui_topbar import build_topbar
from .map_gallery import build_map_gallery
from .object_gallery import build_object_gallery
from .theme import (
    ACCENT,
    ACCENT_DARK,
    ACCENT_HOVER,
    BG,
    BORDER,
    CARD,
    CARD_RAISED,
    FONT,
    HEADER,
    MONO_FONT,
    MUTED,
    PANEL,
    PARALLEL_CATS,
    SECONDARY,
    SECONDARY_HOVER,
    SEL_BG,
    SEL_TEXT,
    SUBTLE,
    TEXT,
    TEXT_STRONG,
    TITLE_FONT,
    TOPBAR,
    card_style,
    entry_style,
    primary_button_style,
    secondary_button_style,
)


class ShellLayoutMixin:
    """Build the always-visible source rail and editor workspace."""

    def _build_topbar(self) -> None:
        build_topbar(self)

    def _build_tabs(self) -> None:
        shell = ctk.CTkFrame(self, fg_color=BG)
        shell.pack(fill="both", expand=True, padx=12, pady=(10, 8))
        self.source_panel = ctk.CTkFrame(
            shell, width=286, fg_color=TOPBAR, corner_radius=18,
            border_width=1, border_color=BORDER,
        )
        self.source_panel.pack(side="left", fill="y", padx=(0, 10))
        self.source_panel.pack_propagate(False)
        self._build_source_panel(self.source_panel)
        content = ctk.CTkFrame(shell, fg_color=BG)
        content.pack(side="left", fill="both", expand=True)
        self.tabs = ctk.CTkTabview(
            content, fg_color=BG,
            segmented_button_selected_color=ACCENT_DARK,
            segmented_button_selected_hover_color=ACCENT_HOVER,
            segmented_button_unselected_color=CARD,
            segmented_button_unselected_hover_color=CARD_RAISED,
            text_color=TEXT,
        )
        self.tabs.pack(fill="both", expand=True)
        self.editor_tab_labels = (
            "总览", "对象编辑器", "地图信息", "场景放置", "触发指令",
            "合成配方", "孤立对象", "分析报告")
        self.tab_overview = self.tabs.add("总览")
        self.tab_obj = self.tabs.add("对象编辑器")
        self.tab_info = self.tabs.add("地图信息")
        self.tab_pre = self.tabs.add("场景放置")
        self.tab_cmd = self.tabs.add("触发指令")
        self.tab_rec = self.tabs.add("合成配方")
        self.tab_orphan = self.tabs.add("孤立对象")
        self.tab_analysis = self.tabs.add("分析报告")
        self._build_overview_tab(self.tab_overview)
        self._build_obj_tab(self.tab_obj)
        self._build_info_tab(self.tab_info)
        self._build_preplaced_tab(self.tab_pre)
        self._build_cmd_tab(self.tab_cmd)
        self._build_rec_tab(self.tab_rec)
        self._build_orphan_tab(self.tab_orphan)
        self._build_analysis_tab(self.tab_analysis)
        self._refresh_editor_reports()

    def _build_source_panel(self, parent) -> None:
        ctk.CTkLabel(parent, text="图源", font=(FONT, 12, "bold"),
                     text_color=MUTED, anchor="w").pack(fill="x", padx=14, pady=(12, 5))
        self.mode_seg = ctk.CTkSegmentedButton(
            parent, values=["对战图", "战役图"], command=self._on_mode_change,
            font=(FONT, 12, "bold"), height=30,
            selected_color=ACCENT_DARK, selected_hover_color=ACCENT_HOVER,
            unselected_color=CARD, unselected_hover_color=CARD_RAISED,
            fg_color=PANEL, text_color=TEXT)
        self.mode_seg.set("对战图")
        self.mode_seg.pack(fill="x", padx=12)
        self.left_brow = ctk.CTkFrame(parent, fg_color="transparent")
        self.left_brow.pack(fill="x", padx=12, pady=(10, 6))
        ctk.CTkButton(self.left_brow, text="选择目录", height=30, font=(FONT, 12, "bold"),
                      command=self.on_pick_dir,
                      **secondary_button_style()).pack(side="left", fill="x", expand=True)
        ctk.CTkButton(self.left_brow, text="⟳", width=30, height=30, font=(FONT, 14),
                      fg_color=SECONDARY, hover_color=SECONDARY_HOVER, text_color=TEXT,
                      corner_radius=6, command=self.on_refresh_dir).pack(side="right", padx=(5, 0))
        self.left_title = ctk.CTkLabel(parent, text="地图列表", font=(FONT, 12, "bold"),
                                       text_color=TEXT_STRONG, anchor="w")
        self.left_title.pack(fill="x", padx=14)
        self.map_search = tk.StringVar()
        search = ctk.CTkEntry(parent, textvariable=self.map_search, height=30, font=(FONT, 11),
                              justify="center", placeholder_text="回车搜索地图",
                              **entry_style())
        search.pack(fill="x", padx=12, pady=(0, 6))
        search.bind("<Return>", lambda *_: self._populate_left())
        self._attach_ctx_menu(search, paste=True)
        self.map_gallery = build_map_gallery(parent)
        legacy_maps = tk.Frame(parent, bg=CARD)
        self.map_list = ttk.Treeview(legacy_maps, show="tree", selectmode="browse")
        self.map_list.column("#0", stretch=False)
        mvsb = ttk.Scrollbar(legacy_maps, orient="vertical", command=self.map_list.yview)
        mhsb = ttk.Scrollbar(legacy_maps, orient="horizontal", command=self.map_list.xview)
        self.map_list.configure(yscrollcommand=mvsb.set, xscrollcommand=mhsb.set)
        self.map_list.bind("<Double-1>", self._on_map_pick)
        self.map_list.bind("<<TreeviewOpen>>", self._on_tree_open)
        self._map_gallery_entries = []
        self._render_map_gallery()
        self._dir_maps = []

    def _build_obj_tab(self, parent) -> None:
        ctrl = ctk.CTkFrame(parent, fg_color=BG)
        ctrl.pack(fill="x", padx=2, pady=(2, 8))
        self.search_var = tk.StringVar()
        search = ctk.CTkEntry(
            ctrl, textvariable=self.search_var, height=38, font=(FONT, 13),
            justify="center",
            placeholder_text='回车搜索：名称 / ID / 字段内容    %词%=包含    ="…"=精准    && / ||',
            **entry_style())
        search.pack(fill="x")
        search.bind("<Return>", lambda *_: self._refresh_list())
        self._attach_ctx_menu(search, paste=True)
        body = ctk.CTkFrame(parent, fg_color=BG)
        body.pack(fill="both", expand=True)
        paned = build_deferred_horizontal_paned(body)
        paned.pack(fill="both", expand=True)
        self.paned = paned
        self._register_paned_window(OBJECT_EDITOR_PANE_KEY, paned)
        self.col_trees = {}
        self.col_results = {}
        self.col_headers = {}
        self.active_object_category = PARALLEL_CATS[0]
        self.object_gallery = build_object_gallery(paned, self._on_object_category)
        self.object_gallery_hint = self.object_gallery.hint
        self.object_cat_buttons = self.object_gallery.buttons
        self.object_cards = self.object_gallery.cards
        add_deferred_pane(paned, self.object_gallery.container, minsize=430, stretch="always")
        legacy = tk.Frame(self.object_gallery.container)
        for cat in PARALLEL_CATS:
            self.col_headers[cat] = ctk.CTkLabel(self.object_gallery.container, text=cat)
            tree = ttk.Treeview(legacy, show="tree", selectmode="browse")
            tree.column("#0", width=80, minwidth=50, stretch=False, anchor="w")
            hsb = ttk.Scrollbar(legacy, orient="horizontal", command=tree.xview)
            tree.configure(xscrollcommand=hsb.set)
            tree.bind("<<TreeviewSelect>>", lambda _event, c=cat: self._on_col_select(c))
            self._attach_tree_copy(tree)
            self.col_trees[cat] = tree
            self.col_results[cat] = []
        self._build_detail_panel(paned)
        self._render_object_cards()

    def _build_detail_panel(self, paned) -> None:
        rightp = ctk.CTkFrame(paned, width=380, **card_style())
        detail_head = ctk.CTkFrame(rightp, fg_color="transparent")
        detail_head.pack(fill="x", padx=12, pady=(12, 2))
        blank_icon = Image.new("RGBA", (36, 36), (0, 0, 0, 0))
        self.detail_blank_icon = ctk.CTkImage(light_image=blank_icon, dark_image=blank_icon, size=(36, 36))
        self.detail_icon_image = self.detail_blank_icon
        self.detail_icon = ctk.CTkLabel(
            detail_head, text="", image=self.detail_icon_image, width=42, height=42,
            fg_color=PANEL, corner_radius=10)
        self.detail_icon.pack(side="left", padx=(0, 10))
        detail_text = ctk.CTkFrame(detail_head, fg_color="transparent")
        detail_text.pack(side="left", fill="x", expand=True)
        self.detail_title = ctk.CTkLabel(
            detail_text, text="选择对象查看详情", font=(FONT, 15, "bold"),
            text_color=TEXT_STRONG, anchor="w", justify="left", wraplength=420)
        self.detail_title.pack(fill="x")
        self.detail_sub = ctk.CTkLabel(
            rightp, text="", font=(FONT, 11), text_color=SUBTLE,
            anchor="w", wraplength=460, justify="left")
        self.detail_sub.pack(fill="x", padx=12)
        self.detail = ctk.CTkTextbox(
            rightp, font=(MONO_FONT, 12), fg_color=PANEL, text_color=TEXT,
            border_width=1, border_color=BORDER, wrap="word")
        self.detail.pack(fill="both", expand=True, padx=10, pady=10)
        self.detail.configure(state="disabled")
        self._attach_ctx_menu(self.detail, copy_all=True)
        add_deferred_pane(paned, rightp, minsize=300, stretch="never")

    def _build_statusbar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color=TOPBAR, corner_radius=0, height=32,
                           border_width=1, border_color=BORDER)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)
        self.status = ctk.CTkLabel(bar, text="就绪 · 点击「打开地图」开始", anchor="w",
                                   font=(FONT, 12), text_color=SUBTLE)
        self.status.pack(fill="both", expand=True, padx=16)

    def _setup_tree_style(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Treeview", background=CARD, fieldbackground=CARD,
                        foreground=TEXT, rowheight=31, borderwidth=0,
                        relief="flat", font=(FONT, 11))
        style.configure("Treeview.Heading", background=HEADER, foreground=TEXT_STRONG,
                        font=(FONT, 11, "bold"), borderwidth=0, relief="flat")
        style.map("Treeview", background=[("selected", SEL_BG)], foreground=[("selected", SEL_TEXT)])
        style.map("Treeview.Heading", background=[("active", CARD_RAISED)])
        style.configure("Vertical.TScrollbar", background=SECONDARY, troughcolor=PANEL,
                        borderwidth=0, arrowsize=11)
        style.configure("Horizontal.TScrollbar", background=SECONDARY, troughcolor=PANEL,
                        borderwidth=0, arrowsize=11)
