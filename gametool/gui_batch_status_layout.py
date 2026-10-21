"""Widget layout for validated three-axis batch status."""
# pyright: reportAttributeAccessIssue=false, reportUninitializedInstanceVariable=false

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import customtkinter as ctk

from .theme import BG, BORDER, CARD, FONT, MUTED, PANEL, TEXT

_COLUMNS = (
    ("map", "地图", 250),
    ("publication", "发布", 80),
    ("archive", "归档", 90),
    ("knowledge", "知识", 80),
    ("reasons", "原因", 180),
    ("source_coverage", "源覆盖缺口", 95),
    ("gaps", "路径/引用", 105),
    ("filtered", "过滤字段", 85),
    ("relations", "关系部分", 85),
    ("blocks", "原始/损坏/受限", 125),
)


class BatchStatusLayoutMixin:
    """Build the bounded-worker batch result selector and ledger."""

    def _build_batch_status_tab(self, parent) -> None:
        controls = ctk.CTkFrame(parent, fg_color=BG)
        controls.pack(fill="x", padx=6, pady=8)
        self.batch_status_pick = ctk.CTkButton(
            controls, text="选择批量结果", command=self._choose_batch_status_root
        )
        self.batch_status_pick.pack(side="left")
        self.batch_status_label = ctk.CTkLabel(
            controls,
            text="未选择已验证的批量结果",
            font=(FONT, 12),
            text_color=MUTED,
            anchor="w",
        )
        self.batch_status_label.pack(side="left", fill="x", expand=True, padx=10)
        frame = ctk.CTkFrame(
            parent, fg_color=CARD, corner_radius=12, border_width=1, border_color=BORDER
        )
        frame.pack(fill="both", expand=True, padx=4, pady=6)
        inner = tk.Frame(frame, bg=CARD)
        inner.pack(fill="both", expand=True, padx=8, pady=8)
        self.batch_status_tree = ttk.Treeview(
            inner, columns=tuple(item[0] for item in _COLUMNS), show="headings"
        )
        for key, title, width in _COLUMNS:
            self.batch_status_tree.heading(key, text=title)
            self.batch_status_tree.column(key, width=width, stretch=False)
        ybar = ttk.Scrollbar(
            inner, orient="vertical", command=self.batch_status_tree.yview
        )
        xbar = ttk.Scrollbar(
            inner, orient="horizontal", command=self.batch_status_tree.xview
        )
        self.batch_status_tree.configure(
            yscrollcommand=ybar.set, xscrollcommand=xbar.set
        )
        ybar.pack(side="right", fill="y")
        xbar.pack(side="bottom", fill="x")
        self.batch_status_tree.pack(side="left", fill="both", expand=True)
        self._attach_tree_copy(self.batch_status_tree)
        self.batch_status_detail = ctk.CTkTextbox(
            parent,
            height=85,
            fg_color=PANEL,
            text_color=TEXT,
            border_width=1,
            border_color=BORDER,
        )
        self.batch_status_detail.pack(fill="x", padx=8, pady=(0, 8))
        self.batch_status_detail.configure(state="disabled")
        self._attach_ctx_menu(self.batch_status_detail, copy_all=True)
