"""Clean map list surface used beside the object gallery."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import customtkinter as ctk

from .theme import (
    ACCENT_DARK,
    ACCENT_HOVER,
    BORDER,
    CARD,
    CARD_RAISED,
    FONT,
    PANEL,
    SECONDARY,
    SECONDARY_HOVER,
    SUBTLE,
    TEXT,
    TEXT_STRONG,
)


@dataclass(frozen=True, slots=True)
class MapEntry:
    iid: str
    title: str
    subtitle: str
    action: str
    depth: int = 0


@dataclass(slots=True)
class MapGallery:
    list_frame: ctk.CTkScrollableFrame


def build_map_gallery(parent: ctk.CTkBaseClass) -> MapGallery:
    list_frame = ctk.CTkScrollableFrame(
        parent, fg_color="#fbfdff", corner_radius=14,
        border_width=1, border_color=BORDER,
        scrollbar_button_color=SECONDARY,
        scrollbar_button_hover_color=SECONDARY_HOVER,
    )
    list_frame.pack(fill="both", expand=True, padx=6, pady=6)
    list_frame.grid_columnconfigure(0, weight=1)
    return MapGallery(list_frame=list_frame)


def render_map_gallery(
    gallery: MapGallery,
    entries: Sequence[MapEntry],
    open_node: Callable[[str], None],
) -> None:
    for child in gallery.list_frame.winfo_children():
        child.destroy()
    if not entries:
        _render_empty(gallery)
        return
    for row, entry in enumerate(entries):
        _render_entry(gallery, row, entry, open_node)


def _render_empty(gallery: MapGallery) -> None:
    empty = ctk.CTkFrame(
        gallery.list_frame, fg_color=PANEL, corner_radius=14,
        border_width=1, border_color=BORDER,
    )
    empty.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
    ctk.CTkLabel(
        empty, text="还没有地图", font=(FONT, 13, "bold"),
        text_color=TEXT_STRONG,
    ).pack(padx=12, pady=(16, 4))
    ctk.CTkLabel(
        empty, text="选择目录后会显示地图卡片。",
        font=(FONT, 11), text_color=SUBTLE,
    ).pack(padx=12, pady=(0, 16))


def _render_entry(
    gallery: MapGallery,
    row: int,
    entry: MapEntry,
    open_node: Callable[[str], None],
) -> None:
    pad_left = 8 + entry.depth * 16
    card = ctk.CTkFrame(
        gallery.list_frame, fg_color=CARD if row % 2 == 0 else "#f7fbff",
        corner_radius=14, border_width=1, border_color=BORDER,
    )
    card.grid(row=row, column=0, sticky="ew", padx=(pad_left, 8), pady=5)
    ctk.CTkLabel(
        card, text=entry.title, font=(FONT, 12, "bold"),
        text_color=TEXT_STRONG, anchor="w", wraplength=280,
    ).pack(fill="x", padx=10, pady=(9, 0))
    ctk.CTkLabel(
        card, text=entry.subtitle, font=(FONT, 10),
        text_color=SUBTLE, anchor="w", wraplength=280,
    ).pack(fill="x", padx=10, pady=(2, 7))
    ctk.CTkButton(
        card, text=entry.action, height=26, font=(FONT, 11, "bold"),
        fg_color=ACCENT_DARK if entry.depth == 0 else SECONDARY,
        hover_color=ACCENT_HOVER if entry.depth == 0 else CARD_RAISED,
        text_color="#ffffff" if entry.depth == 0 else TEXT,
        corner_radius=13, command=lambda node=entry.iid: open_node(node),
    ).pack(fill="x", padx=10, pady=(0, 9))
