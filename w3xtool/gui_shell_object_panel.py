"""Object editor and detail panel construction for the main GUI shell."""

# pyright: reportArgumentType=false
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Protocol

import customtkinter as ctk
from PIL import Image

from .deferred_paned import add_deferred_pane, build_deferred_horizontal_paned
from .gui_pane_state import OBJECT_EDITOR_PANE_KEY
from .map_data import GameObject
from .object_gallery import ObjectGallery, build_object_gallery
from .theme import (
    BG,
    BORDER,
    FONT,
    MONO_FONT,
    PANEL,
    PARALLEL_CATS,
    SUBTLE,
    TEXT,
    TEXT_STRONG,
    card_style,
    entry_style,
)


class ObjectPanelHost(Protocol):
    """Shell members initialized by the object-browser and detail builders."""

    search_var: tk.StringVar
    paned: tk.PanedWindow
    col_trees: dict[str, ttk.Treeview]
    col_results: dict[str, list[GameObject]]
    col_headers: dict[str, ctk.CTkLabel]
    active_object_category: str
    object_gallery: ObjectGallery
    object_gallery_hint: ctk.CTkLabel
    object_cat_buttons: dict[str, ctk.CTkButton]
    object_cards: ttk.Treeview
    detail_blank_icon: ctk.CTkImage
    detail_icon_image: ctk.CTkImage
    detail_icon: ctk.CTkLabel
    detail_title: ctk.CTkLabel
    detail_sub: ctk.CTkLabel
    detail: ctk.CTkTextbox

    def _refresh_list(self) -> None: ...

    def _attach_ctx_menu(
        self,
        widget: ctk.CTkEntry | ctk.CTkTextbox,
        *,
        paste: bool = False,
        copy_all: bool = False,
    ) -> None: ...

    def _register_paned_window(self, name: str, paned: tk.PanedWindow) -> None: ...

    def _on_object_category(self, category: str) -> None: ...

    def _attach_tree_copy(self, tree: ttk.Treeview) -> None: ...

    def _on_col_select(self, category: str) -> None: ...

    def _build_object_text_controls(self, parent: ctk.CTkFrame) -> None: ...

    def _render_object_cards(self) -> None: ...


def build_object_tab(host: ObjectPanelHost, parent: ctk.CTkFrame) -> None:
    """Build searchable object lists and the selected-object evidence pane."""
    ctrl = ctk.CTkFrame(parent, fg_color=BG)
    ctrl.pack(fill="x", padx=2, pady=(2, 8))
    host.search_var = tk.StringVar()
    search = ctk.CTkEntry(
        ctrl,
        textvariable=host.search_var,
        height=38,
        font=(FONT, 13),
        justify="center",
        placeholder_text='回车搜索：名称 / ID / 字段内容    %词%=包含    ="…"=精准    && / ||',
        **entry_style(),
    )
    search.pack(fill="x")
    search.bind("<Return>", lambda *_: host._refresh_list())
    host._attach_ctx_menu(search, paste=True)
    body = ctk.CTkFrame(parent, fg_color=BG)
    body.pack(fill="both", expand=True)
    paned = build_deferred_horizontal_paned(body)
    paned.pack(fill="both", expand=True)
    host.paned = paned
    host._register_paned_window(OBJECT_EDITOR_PANE_KEY, paned)
    host.col_trees = {}
    host.col_results = {}
    host.col_headers = {}
    host.active_object_category = PARALLEL_CATS[0]
    host.object_gallery = build_object_gallery(paned, host._on_object_category)
    host.object_gallery_hint = host.object_gallery.hint
    host.object_cat_buttons = host.object_gallery.buttons
    host.object_cards = host.object_gallery.cards
    add_deferred_pane(
        paned, host.object_gallery.container, minsize=430, stretch="always"
    )
    legacy = tk.Frame(host.object_gallery.container)
    for category in PARALLEL_CATS:
        host.col_headers[category] = ctk.CTkLabel(
            host.object_gallery.container, text=category
        )
        tree = ttk.Treeview(legacy, show="tree", selectmode="browse")
        tree.column("#0", width=80, minwidth=50, stretch=False, anchor="w")
        hsb = ttk.Scrollbar(legacy, orient="horizontal", command=tree.xview)
        tree.configure(xscrollcommand=hsb.set)
        tree.bind(
            "<<TreeviewSelect>>", lambda _event, c=category: host._on_col_select(c)
        )
        host._attach_tree_copy(tree)
        host.col_trees[category] = tree
        host.col_results[category] = []
    build_detail_panel(host, paned)
    host._render_object_cards()


def build_detail_panel(host: ObjectPanelHost, paned: tk.PanedWindow) -> None:
    """Build icon, complete-text controls, and detail textbox."""
    rightp = ctk.CTkFrame(paned, width=380, **card_style())
    detail_head = ctk.CTkFrame(rightp, fg_color="transparent")
    detail_head.pack(fill="x", padx=12, pady=(12, 2))
    blank_icon = Image.new("RGBA", (36, 36), (0, 0, 0, 0))
    host.detail_blank_icon = ctk.CTkImage(
        light_image=blank_icon, dark_image=blank_icon, size=(36, 36)
    )
    host.detail_icon_image = host.detail_blank_icon
    host.detail_icon = ctk.CTkLabel(
        detail_head,
        text="",
        image=host.detail_icon_image,
        width=42,
        height=42,
        fg_color=PANEL,
        corner_radius=10,
    )
    host.detail_icon.pack(side="left", padx=(0, 10))
    detail_text = ctk.CTkFrame(detail_head, fg_color="transparent")
    detail_text.pack(side="left", fill="x", expand=True)
    host.detail_title = ctk.CTkLabel(
        detail_text,
        text="选择对象查看详情",
        font=(FONT, 15, "bold"),
        text_color=TEXT_STRONG,
        anchor="w",
        justify="left",
        wraplength=420,
    )
    host.detail_title.pack(fill="x")
    host.detail_sub = ctk.CTkLabel(
        rightp,
        text="",
        font=(FONT, 11),
        text_color=SUBTLE,
        anchor="w",
        wraplength=460,
        justify="left",
    )
    host.detail_sub.pack(fill="x", padx=12)
    host._build_object_text_controls(rightp)
    host.detail = ctk.CTkTextbox(
        rightp,
        font=(MONO_FONT, 12),
        fg_color=PANEL,
        text_color=TEXT,
        border_width=1,
        border_color=BORDER,
        wrap="word",
    )
    host.detail.pack(fill="both", expand=True, padx=10, pady=10)
    host.detail.configure(state="disabled")
    host._attach_ctx_menu(host.detail, copy_all=True)
    add_deferred_pane(paned, rightp, minsize=300, stretch="never")
