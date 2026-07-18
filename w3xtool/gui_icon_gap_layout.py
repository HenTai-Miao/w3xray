"""Widget construction for the strict icon-gap workspace."""
# pyright: reportAttributeAccessIssue=false, reportUninitializedInstanceVariable=false

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import customtkinter as ctk

from .theme import (
    BG,
    BORDER,
    CARD,
    FONT,
    MONO_FONT,
    MUTED,
    PANEL,
    SECONDARY,
    SECONDARY_HOVER,
    TEXT,
)

_COLUMNS = (
    ("reason", "原因", 170),
    ("category", "分类", 90),
    ("rawcode", "Rawcode", 90),
    ("path", "路径", 330),
    ("archive", "归档", 100),
    ("refs", "引用", 60),
)


class IconGapLayoutMixin:
    """Build searchable, scrollable, read-only icon evidence controls."""

    def _build_icon_gap_tab(self, parent) -> None:
        controls = ctk.CTkFrame(parent, fg_color=BG)
        controls.pack(fill="x", padx=4, pady=8)
        self.icon_gap_search = tk.StringVar()
        search = ctk.CTkEntry(
            controls,
            textvariable=self.icon_gap_search,
            placeholder_text="搜索路径、原因、分类或 Rawcode",
            height=36,
        )
        search.pack(side="left", fill="x", expand=True, padx=(0, 6))
        search.bind("<Return>", lambda _event: self._refresh_icon_gaps())
        self._attach_ctx_menu(search, paste=True)
        self.icon_gap_scope = ctk.CTkSegmentedButton(
            controls,
            values=["当前地图", "批量结果"],
            command=lambda _value: self._refresh_icon_gaps(),
        )
        self.icon_gap_scope.set("当前地图")
        self.icon_gap_scope.pack(side="right", padx=(6, 0))
        self.icon_gap_mode = ctk.CTkSegmentedButton(
            controls,
            values=["未解析", "候选（未采用）"],
            command=lambda _value: self._refresh_icon_gaps(),
        )
        self.icon_gap_mode.set("未解析")
        self.icon_gap_mode.pack(side="right")
        filters = ctk.CTkFrame(parent, fg_color="transparent")
        filters.pack(fill="x", padx=4, pady=(0, 6))
        self.icon_gap_reason = ctk.CTkComboBox(
            filters,
            values=["全部"],
            width=170,
            state="readonly",
            command=lambda _value: self._refresh_icon_gaps(),
        )
        self.icon_gap_reason.set("全部")
        self.icon_gap_reason.pack(side="left", padx=(0, 6))
        self.icon_gap_category = ctk.CTkComboBox(
            filters,
            values=["全部"],
            width=110,
            state="readonly",
            command=lambda _value: self._refresh_icon_gaps(),
        )
        self.icon_gap_category.set("全部")
        self.icon_gap_category.pack(side="left", padx=(0, 6))
        self.icon_gap_archive = ctk.CTkComboBox(
            filters,
            values=["全部"],
            width=130,
            state="readonly",
            command=lambda _value: self._refresh_icon_gaps(),
        )
        self.icon_gap_archive.set("全部")
        self.icon_gap_archive.pack(side="left")
        self.icon_gap_status = ctk.CTkLabel(
            parent,
            text="打开地图后显示严格图标缺口",
            font=(FONT, 12),
            text_color=MUTED,
            anchor="w",
        )
        self.icon_gap_status.pack(fill="x", padx=8)
        frame = ctk.CTkFrame(
            parent, fg_color=CARD, corner_radius=12, border_width=1, border_color=BORDER
        )
        frame.pack(fill="both", expand=True, padx=4, pady=6)
        inner = tk.Frame(frame, bg=CARD)
        inner.pack(fill="both", expand=True, padx=8, pady=8)
        self.icon_gap_tree = ttk.Treeview(
            inner,
            columns=tuple(item[0] for item in _COLUMNS),
            show="headings",
            selectmode="browse",
        )
        for name, title, width in _COLUMNS:
            self.icon_gap_tree.heading(name, text=title)
            self.icon_gap_tree.column(name, width=width, stretch=False)
        ybar = ttk.Scrollbar(inner, orient="vertical", command=self.icon_gap_tree.yview)
        xbar = ttk.Scrollbar(
            inner, orient="horizontal", command=self.icon_gap_tree.xview
        )
        self.icon_gap_tree.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        ybar.pack(side="right", fill="y")
        xbar.pack(side="bottom", fill="x")
        self.icon_gap_tree.pack(side="left", fill="both", expand=True)
        self.icon_gap_tree.bind("<<TreeviewSelect>>", self._show_icon_gap_evidence)
        self.icon_gap_tree.bind(
            "<Double-1>", lambda _event: self._open_icon_gap_object()
        )
        self._attach_tree_copy(self.icon_gap_tree)
        actions = ctk.CTkFrame(parent, fg_color="transparent")
        actions.pack(fill="x", padx=8)
        self.icon_gap_open_button = ctk.CTkButton(
            actions,
            text="打开对象",
            command=self._open_icon_gap_object,
            state="disabled",
            fg_color=SECONDARY,
            hover_color=SECONDARY_HOVER,
            text_color=TEXT,
        )
        self.icon_gap_open_button.pack(side="left")
        self.icon_gap_detail = ctk.CTkTextbox(
            parent,
            height=150,
            font=(MONO_FONT, 12),
            fg_color=PANEL,
            text_color=TEXT,
            border_width=1,
            border_color=BORDER,
        )
        self.icon_gap_detail.pack(fill="x", padx=8, pady=8)
        self.icon_gap_detail.configure(state="disabled")
        self._attach_ctx_menu(self.icon_gap_detail, copy_all=True)
        self.icon_gap_rows = {}
