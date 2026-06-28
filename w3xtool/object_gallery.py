"""Anime-styled object card gallery for the main object browser."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Final

import customtkinter as ctk
from PIL import ImageTk

from .api import GameObject
from .theme import (
    ACCENT_DARK,
    ACCENT_HOVER,
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

MAX_VISIBLE_CARDS: Final = 240
CARD_HEIGHT: Final = 126


@dataclass(slots=True)
class ObjectGallery:
    """Visible object browser widgets plus image references."""

    container: ctk.CTkFrame
    hint: ctk.CTkLabel
    buttons: dict[str, ctk.CTkButton]
    cards: ctk.CTkScrollableFrame
    card_images: list[ImageTk.PhotoImage] = field(default_factory=list)


def build_object_gallery(
    parent: ctk.CTkBaseClass,
    on_category: Callable[[str], None],
) -> ObjectGallery:
    container = ctk.CTkFrame(
        parent, width=620, fg_color=CARD, corner_radius=18,
        border_width=1, border_color=BORDER,
    )
    header = ctk.CTkFrame(container, fg_color="transparent")
    header.pack(fill="x", padx=14, pady=(12, 8))
    title_box = ctk.CTkFrame(header, fg_color="transparent")
    title_box.pack(side="left", fill="x", expand=True)
    ctk.CTkLabel(
        title_box, text="对象档案馆", font=(FONT, 16, "bold"),
        text_color=TEXT_STRONG, anchor="w",
    ).pack(fill="x")
    ctk.CTkLabel(
        title_box, text="按类型翻阅地图对象卡片",
        font=(FONT, 11), text_color=SUBTLE, anchor="w",
    ).pack(fill="x", pady=(2, 0))
    hint = ctk.CTkLabel(header, text="等待加载地图", font=(FONT, 11), text_color=SUBTLE)
    hint.pack(side="right")

    buttons: dict[str, ctk.CTkButton] = {}
    cat_bar = ctk.CTkFrame(
        container, fg_color=PANEL, corner_radius=18,
        border_width=1, border_color=BORDER,
    )
    cat_bar.pack(fill="x", padx=14, pady=(0, 10))
    for cat in PARALLEL_CATS:
        btn = ctk.CTkButton(
            cat_bar, text=cat, height=34, width=94,
            font=(FONT, 12, "bold"), fg_color="transparent", hover_color=CARD_RAISED,
            text_color=CATEGORY_COLORS.get(cat, TEXT),
            corner_radius=17, command=lambda category=cat: on_category(category),
        )
        btn.pack(side="left", padx=4, pady=4)
        buttons[cat] = btn

    cards = ctk.CTkScrollableFrame(
        container, fg_color="#fbfdff", scrollbar_button_color=SECONDARY,
        scrollbar_button_hover_color=SECONDARY_HOVER,
    )
    cards.pack(fill="both", expand=True, padx=10, pady=(0, 10))
    cards.grid_columnconfigure(0, weight=1, uniform="object_cards")
    cards.grid_columnconfigure(1, weight=1, uniform="object_cards")
    return ObjectGallery(container=container, hint=hint, buttons=buttons, cards=cards)


def render_object_gallery(
    gallery: ObjectGallery,
    active_category: str,
    results_by_category: Mapping[str, list[GameObject]],
    show_detail: Callable[[GameObject], None],
    get_photo: Callable[[str], ImageTk.PhotoImage | None],
) -> None:
    for child in gallery.cards.winfo_children():
        child.destroy()
    gallery.card_images.clear()

    category = active_category if active_category in PARALLEL_CATS else PARALLEL_CATS[0]
    results = results_by_category.get(category, [])
    _refresh_category_buttons(gallery, category, results_by_category)
    gallery.hint.configure(text=f"{category} · {len(results)} 个对象")
    if not results:
        _render_empty_state(gallery, category)
        return

    for index, obj in enumerate(results[:MAX_VISIBLE_CARDS]):
        _render_card(
            gallery=gallery,
            obj=obj,
            index=index,
            show_detail=show_detail,
            get_photo=get_photo,
        )
    if len(results) > MAX_VISIBLE_CARDS:
        _render_limit_notice(gallery, len(results))


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
    empty.grid(row=0, column=0, columnspan=2, sticky="nsew", padx=8, pady=8)
    ctk.CTkLabel(
        empty, text=f"{category} 没有匹配对象",
        font=(FONT, 14, "bold"), text_color=TEXT_STRONG,
    ).pack(padx=16, pady=(18, 4))
    ctk.CTkLabel(
        empty, text="换一个分类，或清空搜索条件后回车刷新。",
        font=(FONT, 12), text_color=SUBTLE,
    ).pack(padx=16, pady=(0, 18))


def _render_card(
    gallery: ObjectGallery,
    obj: GameObject,
    index: int,
    show_detail: Callable[[GameObject], None],
    get_photo: Callable[[str], ImageTk.PhotoImage | None],
) -> None:
    color = CATEGORY_COLORS.get(obj.category, ACCENT_DARK)
    card = ctk.CTkFrame(
        gallery.cards, height=CARD_HEIGHT,
        fg_color=CARD if index % 2 == 0 else "#f7fbff",
        corner_radius=18, border_width=1, border_color=BORDER,
    )
    card.grid(row=index // 2, column=index % 2, sticky="nsew", padx=7, pady=7)
    card.grid_propagate(False)

    accent = ctk.CTkFrame(card, width=7, fg_color=color, corner_radius=8)
    accent.pack(side="left", fill="y", padx=(8, 0), pady=8)
    content = ctk.CTkFrame(card, fg_color="transparent")
    content.pack(side="left", fill="both", expand=True, padx=10, pady=8)

    top = ctk.CTkFrame(content, fg_color="transparent")
    top.pack(fill="x")
    photo = get_photo(getattr(obj, "icon", ""))
    if photo is not None:
        gallery.card_images.append(photo)
        ctk.CTkLabel(top, text="", image=photo, width=28).pack(side="left", padx=(0, 8))
    title = ctk.CTkLabel(
        top, text=obj.name, font=(FONT, 13, "bold"),
        text_color=TEXT_STRONG, anchor="w", justify="left", wraplength=230,
    )
    title.pack(side="left", fill="x", expand=True)

    meta = f"{obj.obj_id} · 基础 {obj.base_id} · {_object_kind(obj)}"
    ctk.CTkLabel(
        content, text=meta, font=(FONT, 11),
        text_color=SUBTLE, anchor="w",
    ).pack(fill="x", pady=(5, 0))
    ctk.CTkLabel(
        content, text=_field_summary(obj), font=(FONT, 11),
        text_color=TEXT, anchor="w", wraplength=260,
    ).pack(fill="x", pady=(3, 0))
    ctk.CTkButton(
        content, text="查看档案", height=26, width=84,
        font=(FONT, 11, "bold"), fg_color=color,
        hover_color=ACCENT_HOVER, text_color="#ffffff", corner_radius=13,
        command=lambda item=obj: show_detail(item),
    ).pack(anchor="e", pady=(5, 0))


def _render_limit_notice(gallery: ObjectGallery, total: int) -> None:
    row = (MAX_VISIBLE_CARDS + 1) // 2
    notice = ctk.CTkLabel(
        gallery.cards, text=f"已显示前 {MAX_VISIBLE_CARDS} 个，共 {total} 个。继续搜索可缩小范围。",
        font=(FONT, 11), text_color=SUBTLE,
    )
    notice.grid(row=row, column=0, columnspan=2, sticky="ew", padx=8, pady=10)


def _object_kind(obj: GameObject) -> str:
    ext = getattr(obj, "ext", "")
    if ext == "script":
        return "脚本"
    if ext == "base":
        return "原版"
    if obj.is_custom:
        return "自定义"
    return "原始"


def _field_summary(obj: GameObject) -> str:
    if not obj.fields:
        return "无修改字段"
    first = obj.fields[0]
    label = str(first[0]) if len(first) > 0 else "字段"
    value = str(first[1]) if len(first) > 1 else ""
    if len(value) > 34:
        value = f"{value[:34]}..."
    suffix = f" 等 {len(obj.fields)} 项" if len(obj.fields) > 1 else ""
    return f"{label}: {value}{suffix}"
