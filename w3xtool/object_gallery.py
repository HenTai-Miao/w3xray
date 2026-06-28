"""Compact object list for the main object browser."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final

import customtkinter as ctk

from .api import GameObject
from .object_gallery_cards import render_object_card
from .theme import (
    ACCENT_DARK,
    BORDER,
    CARD,
    CARD_RAISED,
    CATEGORY_COLORS,
    FONT,
    PANEL,
    PARALLEL_CATS,
    SECONDARY,
    SECONDARY_HOVER,
    SUBTLE,
    TEXT,
    TEXT_STRONG,
)

GALLERY_COLUMNS: Final = 1


@dataclass(slots=True)
class ObjectGallery:
    """Visible object browser widgets plus image references."""

    container: ctk.CTkFrame
    hint: ctk.CTkLabel
    buttons: dict[str, ctk.CTkButton]
    cards: ctk.CTkScrollableFrame


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

    cards = ctk.CTkScrollableFrame(
        container, fg_color="#fbfdff", scrollbar_button_color=SECONDARY,
        scrollbar_button_hover_color=SECONDARY_HOVER,
    )
    cards.pack(fill="both", expand=True, padx=10, pady=(0, 8))
    cards.grid_columnconfigure(0, weight=1)
    return ObjectGallery(container=container, hint=hint, buttons=buttons, cards=cards)


def render_object_gallery(
    gallery: ObjectGallery,
    active_category: str,
    results_by_category: Mapping[str, list[GameObject]],
    show_detail: Callable[[GameObject], None],
) -> None:
    for child in gallery.cards.winfo_children():
        child.destroy()

    category = active_category if active_category in PARALLEL_CATS else PARALLEL_CATS[0]
    results = results_by_category.get(category, [])
    _refresh_category_buttons(gallery, category, results_by_category)
    gallery.hint.configure(text=f"{category} · {len(results)} 个对象")
    if not results:
        _render_empty_state(gallery, category)
        return

    for index, obj in enumerate(results):
        render_object_card(
            gallery=gallery,
            obj=obj,
            index=index,
            columns=GALLERY_COLUMNS,
            show_detail=show_detail,
        )


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
    empty = ctk.CTkFrame(
        gallery.cards, fg_color=PANEL, corner_radius=18,
        border_width=1, border_color=BORDER,
    )
    empty.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
    ctk.CTkLabel(
        empty, text=f"{category} 没有匹配对象",
        font=(FONT, 14, "bold"), text_color=TEXT_STRONG,
    ).pack(padx=16, pady=(18, 4))
    ctk.CTkLabel(
        empty, text="换一个分类，或清空搜索条件后回车刷新。",
        font=(FONT, 12), text_color=SUBTLE,
    ).pack(padx=16, pady=(0, 18))
