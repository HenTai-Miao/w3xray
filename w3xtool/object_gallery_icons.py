"""Progressive icon loading for the object gallery table."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from typing import TYPE_CHECKING

from .api import GameObject

if TYPE_CHECKING:
    from .object_gallery import ObjectGallery

ICON_SIZE = 18
ICON_BATCH_SIZE = 64


def cancel_icon_job(gallery: ObjectGallery) -> None:
    if gallery.icon_job is None:
        return
    try:
        gallery.container.after_cancel(gallery.icon_job)
    except tk.TclError:
        pass
    gallery.icon_job = None


def queue_icon_loading(
    gallery: ObjectGallery,
    results: list[GameObject],
    token: int,
    get_icon: Callable[[str, int], tk.PhotoImage | None] | None,
) -> None:
    if get_icon is None:
        return
    if not any(obj.icon for obj in results):
        return
    gallery.icon_job = gallery.container.after_idle(
        lambda: _load_icon_batch(gallery, results, token, get_icon, 0)
    )


def _load_icon_batch(
    gallery: ObjectGallery,
    results: list[GameObject],
    token: int,
    get_icon: Callable[[str, int], tk.PhotoImage | None],
    start: int,
) -> None:
    gallery.icon_job = None
    if token != gallery.render_token:
        return
    end = min(start + ICON_BATCH_SIZE, len(results))
    for index in range(start, end):
        icon_path = results[index].icon
        if not icon_path:
            continue
        image = get_icon(icon_path, ICON_SIZE)
        if image is None:
            continue
        gallery.icon_images.append(image)
        try:
            gallery.cards.item(str(index), image=image)
        except tk.TclError:
            return
    if end < len(results):
        gallery.icon_job = gallery.container.after(
            10, lambda: _load_icon_batch(gallery, results, token, get_icon, end)
        )
