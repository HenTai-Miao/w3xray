"""Source rail construction for the main GUI shell."""

# pyright: reportArgumentType=false
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Protocol

import customtkinter as ctk

from .map_gallery import MapEntry, MapGallery, build_map_gallery
from .theme import (
    ACCENT_DARK,
    ACCENT_HOVER,
    CARD,
    CARD_RAISED,
    FONT,
    MUTED,
    PANEL,
    SECONDARY,
    SECONDARY_HOVER,
    TEXT,
    TEXT_STRONG,
    entry_style,
    secondary_button_style,
)


class SourcePanelHost(Protocol):
    """Shell members initialized by the persistent source-panel builder."""

    mode_seg: ctk.CTkSegmentedButton
    left_brow: ctk.CTkFrame
    left_title: ctk.CTkLabel
    map_search: tk.StringVar
    map_gallery: MapGallery
    map_list: ttk.Treeview
    _map_gallery_entries: list[MapEntry]
    _dir_maps: list[tuple[str, str]]

    def _on_mode_change(self, mode: str) -> None: ...

    def on_pick_dir(self) -> None: ...

    def on_refresh_dir(self) -> None: ...

    def _populate_left(self) -> None: ...

    def _attach_ctx_menu(self, widget: ctk.CTkEntry, *, paste: bool) -> None: ...

    def _on_map_pick(self, event: tk.Event[tk.Misc]) -> None: ...

    def _on_tree_open(self, event: tk.Event[tk.Misc]) -> None: ...

    def _render_map_gallery(self) -> None: ...


def build_source_panel(host: SourcePanelHost, parent: ctk.CTkFrame) -> None:
    """Build persistent map-source controls outside the editor workspace."""
    ctk.CTkLabel(
        parent, text="图源", font=(FONT, 12, "bold"), text_color=MUTED, anchor="w"
    ).pack(fill="x", padx=14, pady=(12, 5))
    host.mode_seg = ctk.CTkSegmentedButton(
        parent,
        values=["对战图", "战役图"],
        command=host._on_mode_change,
        font=(FONT, 12, "bold"),
        height=30,
        selected_color=ACCENT_DARK,
        selected_hover_color=ACCENT_HOVER,
        unselected_color=CARD,
        unselected_hover_color=CARD_RAISED,
        fg_color=PANEL,
        text_color=TEXT,
    )
    host.mode_seg.set("对战图")
    host.mode_seg.pack(fill="x", padx=12)
    host.left_brow = ctk.CTkFrame(parent, fg_color="transparent")
    host.left_brow.pack(fill="x", padx=12, pady=(10, 6))
    ctk.CTkButton(
        host.left_brow,
        text="选择目录",
        height=30,
        font=(FONT, 12, "bold"),
        command=host.on_pick_dir,
        **secondary_button_style(),
    ).pack(side="left", fill="x", expand=True)
    ctk.CTkButton(
        host.left_brow,
        text="⟳",
        width=30,
        height=30,
        font=(FONT, 14),
        fg_color=SECONDARY,
        hover_color=SECONDARY_HOVER,
        text_color=TEXT,
        corner_radius=6,
        command=host.on_refresh_dir,
    ).pack(side="right", padx=(5, 0))
    host.left_title = ctk.CTkLabel(
        parent,
        text="地图列表",
        font=(FONT, 12, "bold"),
        text_color=TEXT_STRONG,
        anchor="w",
    )
    host.left_title.pack(fill="x", padx=14)
    host.map_search = tk.StringVar()
    search = ctk.CTkEntry(
        parent,
        textvariable=host.map_search,
        height=30,
        font=(FONT, 11),
        justify="center",
        placeholder_text="回车搜索地图",
        **entry_style(),
    )
    search.pack(fill="x", padx=12, pady=(0, 6))
    search.bind("<Return>", lambda *_: host._populate_left())
    host._attach_ctx_menu(search, paste=True)
    host.map_gallery = build_map_gallery(parent)
    legacy_maps = tk.Frame(parent, bg=CARD)
    host.map_list = ttk.Treeview(legacy_maps, show="tree", selectmode="browse")
    host.map_list.column("#0", stretch=False)
    mvsb = ttk.Scrollbar(legacy_maps, orient="vertical", command=host.map_list.yview)
    mhsb = ttk.Scrollbar(legacy_maps, orient="horizontal", command=host.map_list.xview)
    host.map_list.configure(yscrollcommand=mvsb.set, xscrollcommand=mhsb.set)
    host.map_list.bind("<Double-1>", host._on_map_pick)
    host.map_list.bind("<<TreeviewOpen>>", host._on_tree_open)
    host._map_gallery_entries = []
    host._render_map_gallery()
    host._dir_maps = []
