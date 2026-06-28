"""Single object name row rendering for the object list."""
from __future__ import annotations

from collections.abc import Callable
from typing import Final

import customtkinter as ctk

from .api import GameObject
from .theme import (
    ACCENT_DARK,
    BORDER,
    CARD,
    CATEGORY_COLORS,
    FONT,
    TEXT_STRONG,
)

CARD_HEIGHT: Final = 30


def render_object_card(
    gallery,
    obj: GameObject,
    *,
    index: int,
    columns: int,
    show_detail: Callable[[GameObject], None],
) -> None:
    """Render one compact object row with only the name visible."""
    color = CATEGORY_COLORS.get(obj.category, ACCENT_DARK)
    card = ctk.CTkFrame(
        gallery.cards,
        height=CARD_HEIGHT,
        fg_color=CARD if index % 2 == 0 else "#f7fbff",
        corner_radius=8,
        border_width=1,
        border_color=BORDER,
    )
    card.grid(row=index // columns, column=index % columns, sticky="ew", padx=4, pady=2)
    card.grid_propagate(False)
    card.pack_propagate(False)
    _bind_detail(card, obj, show_detail)

    ctk.CTkFrame(card, width=3, fg_color=color, corner_radius=4).pack(
        side="left", fill="y", padx=(6, 0), pady=6
    )
    label = ctk.CTkLabel(
        card,
        text=obj.name,
        font=(FONT, 12, "bold"),
        text_color=TEXT_STRONG,
        anchor="w",
        justify="left",
    )
    label.pack(side="left", fill="x", expand=True, padx=8)
    _bind_detail(label, obj, show_detail)


def _bind_detail(widget, obj: GameObject, show_detail: Callable[[GameObject], None]) -> None:
    widget.bind("<Button-1>", lambda _event, item=obj: show_detail(item))
