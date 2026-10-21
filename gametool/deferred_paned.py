"""Paned-window helpers that avoid live resizing heavy panes during drag."""

from __future__ import annotations

import tkinter as tk
from typing import Literal

from .theme import BG

PaneStretch = Literal["always", "first", "last", "middle", "never"]


def build_deferred_horizontal_paned(parent: tk.Misc) -> tk.PanedWindow:
    """Build a horizontal pane that resizes content after the drag is released."""
    return tk.PanedWindow(
        parent,
        orient="horizontal",
        opaqueresize=False,
        borderwidth=0,
        bg=BG,
        sashrelief="flat",
        sashwidth=8,
        showhandle=False,
    )


def add_deferred_pane(
    paned: tk.PanedWindow,
    child: tk.Widget,
    *,
    minsize: int,
    stretch: PaneStretch,
) -> None:
    paned.add(child, minsize=minsize, stretch=stretch)
