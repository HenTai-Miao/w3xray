"""Compact object list for the main object browser."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from tkinter import ttk

import customtkinter as ctk

from .api import GameObject
from .object_gallery_icons import cancel_icon_job, queue_icon_loading
from .theme import (
    ACCENT_DARK,
    BORDER,
    CARD,
    CARD_RAISED,
    CATEGORY_COLORS,
    FONT,
    PANEL,
    PARALLEL_CATS,
    SUBTLE,
    TEXT,
    TEXT_STRONG,
)


@dataclass(slots=True)
class ObjectGallery:
    """Visible object browser widgets plus image references."""

    container: ctk.CTkFrame
    hint: ctk.CTkLabel
    buttons: dict[str, ctk.CTkButton]
    cards: ttk.Treeview
    active_objects: list[GameObject] = field(default_factory=list)
    icon_images: list[tk.PhotoImage] = field(default_factory=list)
    icon_job: str | None = None
    render_token: int = 0


def build_object_gallery(
    parent: ctk.CTkBaseClass,
    on_category: Callable[[str], None],
) -> ObjectGallery:
    container = ctk.CTkFrame(
        parent, width=620, fg_color=CARD, corner_radius=18,
        border_width=1, border_color=BORDER,
    )
    header = ctk.CTkFrame(container, fg_color="transparent")
    header.pack(fill="x", padx=14, pady=(10, 6))
    title_box = ctk.CTkFrame(header, fg_color="transparent")
    title_box.pack(side="left", fill="x", expand=True)
    ctk.CTkLabel(
        title_box, text="对象档案馆", font=(FONT, 15, "bold"),
        text_color=TEXT_STRONG, anchor="w",
    ).pack(fill="x")
    ctk.CTkLabel(
        title_box, text="单位 · 物品 · 技能 · 科技 · 可破坏物等",
        font=(FONT, 10), text_color=SUBTLE, anchor="w",
    ).pack(fill="x", pady=(1, 0))
    hint = ctk.CTkLabel(header, text="等待加载地图", font=(FONT, 11), text_color=SUBTLE)
    hint.pack(side="right")

    buttons: dict[str, ctk.CTkButton] = {}
    cat_bar = ctk.CTkFrame(
        container, fg_color=PANEL, corner_radius=18,
        border_width=1, border_color=BORDER,
    )
    cat_bar.pack(fill="x", padx=14, pady=(0, 7))
    for index, cat in enumerate(PARALLEL_CATS):
        btn = ctk.CTkButton(
            cat_bar, text=cat, height=26, width=76,
            font=(FONT, 12, "bold"), fg_color="transparent", hover_color=CARD_RAISED,
            text_color=CATEGORY_COLORS.get(cat, TEXT),
            corner_radius=13, command=lambda category=cat: on_category(category),
        )
        btn.grid(row=index // 4, column=index % 4, sticky="ew", padx=3, pady=3)
        cat_bar.grid_columnconfigure(index % 4, weight=1, uniform="object_category")
        buttons[cat] = btn

    list_shell = tk.Frame(
        container,
        bg="#fbfdff",
        highlightthickness=1,
        highlightbackground=BORDER,
        highlightcolor=BORDER,
    )
    list_shell.pack(fill="both", expand=True, padx=10, pady=(0, 8))
    cards = ttk.Treeview(
        list_shell,
        columns=("decimal", "obj_id"),
        show="tree headings",
        selectmode="browse",
    )
    yscroll = ttk.Scrollbar(list_shell, orient="vertical", command=cards.yview)
    xscroll = ttk.Scrollbar(list_shell, orient="horizontal", command=cards.xview)
    cards.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
    cards.heading("#0", text="图标 / 名称", anchor="w")
    cards.heading("decimal", text="十进制", anchor="center")
    cards.heading("obj_id", text="物品ID", anchor="center")
    cards.column("#0", width=270, minwidth=150, stretch=True, anchor="w")
    cards.column("decimal", width=118, minwidth=90, stretch=False, anchor="center")
    cards.column("obj_id", width=92, minwidth=70, stretch=False, anchor="center")
    yscroll.pack(side="right", fill="y")
    xscroll.pack(side="bottom", fill="x")
    cards.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
    return ObjectGallery(container=container, hint=hint, buttons=buttons, cards=cards)


def render_object_gallery(
    gallery: ObjectGallery,
    active_category: str,
    results_by_category: Mapping[str, list[GameObject]],
    show_detail: Callable[[GameObject], None],
    get_icon: Callable[[str, int], tk.PhotoImage | None] | None = None,
) -> None:
    cancel_icon_job(gallery)
    category = active_category if active_category in PARALLEL_CATS else PARALLEL_CATS[0]
    results = results_by_category.get(category, [])
    gallery.active_objects = list(results)
    gallery.icon_images = []
    gallery.render_token += 1
    token = gallery.render_token
    _refresh_category_buttons(gallery, category, results_by_category)
    gallery.hint.configure(text=f"{category} · {len(results)} 个对象")
    gallery.cards.delete(*gallery.cards.get_children())
    gallery.cards.bind(
        "<<TreeviewSelect>>",
        lambda _event: _show_selected_object(gallery, show_detail),
    )
    if not results:
        _render_empty_state(gallery, category)
        return

    for index, obj in enumerate(results):
        gallery.cards.insert(
            "",
            "end",
            iid=str(index),
            text=obj.name or obj.obj_id,
            values=(str(obj.decimal), obj.obj_id),
        )
    queue_icon_loading(gallery, gallery.active_objects, token, get_icon)


def _refresh_category_buttons(
    gallery: ObjectGallery,
    active_category: str,
    results_by_category: Mapping[str, list[GameObject]],
) -> None:
    for cat in PARALLEL_CATS:
        count = len(results_by_category.get(cat, []))
        selected = cat == active_category
        color = CATEGORY_COLORS.get(cat, ACCENT_DARK)
        gallery.buttons[cat].configure(
            text=f"{cat} {count}",
            fg_color=color if selected else "transparent",
            hover_color=color if selected else CARD_RAISED,
            text_color="#ffffff" if selected else color,
        )


def _render_empty_state(gallery: ObjectGallery, category: str) -> None:
    gallery.cards.insert("", "end", iid="__empty__", text=f"{category} 没有匹配对象")


def _show_selected_object(
    gallery: ObjectGallery,
    show_detail: Callable[[GameObject], None],
) -> None:
    selection = gallery.cards.selection()
    if not selection:
        return
    item_id = str(selection[0])
    if not item_id.isdigit():
        return
    index = int(item_id)
    if index >= len(gallery.active_objects):
        return
    show_detail(gallery.active_objects[index])
