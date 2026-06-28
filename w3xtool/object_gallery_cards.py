"""Single object card rendering for the object gallery."""
from __future__ import annotations

from collections.abc import Callable
from typing import Final

import customtkinter as ctk
from PIL import ImageTk

from .api import GameObject
from .theme import (
    ACCENT_DARK,
    ACCENT_HOVER,
    BORDER,
    CARD,
    CATEGORY_COLORS,
    FONT,
    SUBTLE,
    TEXT,
    TEXT_STRONG,
)

CARD_HEIGHT: Final = 70


def render_object_card(
    gallery,
    obj: GameObject,
    *,
    index: int,
    columns: int,
    show_detail: Callable[[GameObject], None],
    get_photo: Callable[[str], ImageTk.PhotoImage | None],
) -> None:
    """Render one compact object card."""
    color = CATEGORY_COLORS.get(obj.category, ACCENT_DARK)
    card = ctk.CTkFrame(
        gallery.cards,
        height=CARD_HEIGHT,
        fg_color=CARD if index % 2 == 0 else "#f7fbff",
        corner_radius=18,
        border_width=1,
        border_color=BORDER,
    )
    card.grid(row=index // columns, column=index % columns, sticky="nsew", padx=5, pady=5)
    card.grid_propagate(False)

    ctk.CTkFrame(card, width=5, fg_color=color, corner_radius=6).pack(
        side="left", fill="y", padx=(7, 0), pady=7
    )
    content = ctk.CTkFrame(card, fg_color="transparent")
    content.pack(side="left", fill="both", expand=True, padx=8, pady=6)
    top = ctk.CTkFrame(content, fg_color="transparent")
    top.pack(fill="x")
    _pack_icon(top, gallery, obj, get_photo)
    ctk.CTkLabel(
        top,
        text=obj.name,
        font=(FONT, 12, "bold"),
        text_color=TEXT_STRONG,
        anchor="w",
        justify="left",
        wraplength=170,
    ).pack(side="left", fill="x", expand=True)
    ctk.CTkButton(
        top,
        text="查看",
        height=22,
        width=50,
        font=(FONT, 10, "bold"),
        fg_color=color,
        hover_color=ACCENT_HOVER,
        text_color="#ffffff",
        corner_radius=11,
        command=lambda item=obj: show_detail(item),
    ).pack(side="right", padx=(6, 0))
    _pack_summary(content, obj)


def _pack_icon(parent, gallery, obj: GameObject, get_photo) -> None:
    photo = get_photo(getattr(obj, "icon", ""))
    if photo is None:
        return
    gallery.card_images.append(photo)
    ctk.CTkLabel(parent, text="", image=photo, width=22).pack(side="left", padx=(0, 6))


def _pack_summary(parent, obj: GameObject) -> None:
    meta = f"{obj.obj_id} · 基础 {obj.base_id} · {_object_kind(obj)}"
    ctk.CTkLabel(parent, text=meta, font=(FONT, 10), text_color=SUBTLE, anchor="w").pack(
        fill="x", pady=(2, 0)
    )
    ctk.CTkLabel(
        parent,
        text=_field_summary(obj),
        font=(FONT, 10),
        text_color=TEXT,
        anchor="w",
        wraplength=250,
    ).pack(fill="x", pady=(1, 0))


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
    if len(value) > 24:
        value = f"{value[:24]}..."
    suffix = f" 等 {len(obj.fields)} 项" if len(obj.fields) > 1 else ""
    return f"{label}: {value}{suffix}"
