"""Icon image cache shared by gallery rows and the detail panel."""

from __future__ import annotations

import customtkinter as ctk
from PIL import Image, ImageTk


class IconCacheMixin:
    def _get_photo(self, icon_path, size=36):
        if not icon_path:
            return None
        key = (icon_path.lower(), size, "ctk")
        if key in self._photo_cache:
            return self._photo_cache[key]
        photo = None
        pil = self._get_icon_pil(icon_path)
        if pil is not None:
            icon = pil.resize((size, size), Image.LANCZOS)
            photo = ctk.CTkImage(light_image=icon, dark_image=icon, size=(size, size))
        self._photo_cache[key] = photo
        return photo

    def _get_tree_photo(self, icon_path, size=18):
        if not icon_path:
            return None
        key = (icon_path.lower(), size, "tree")
        if key in self._photo_cache:
            return self._photo_cache[key]
        photo = None
        pil = self._get_icon_pil(icon_path)
        if pil is not None:
            icon = pil.resize((size, size), Image.LANCZOS)
            photo = ImageTk.PhotoImage(icon)
        self._photo_cache[key] = photo
        return photo

    def _get_icon_pil(self, icon_path):
        if not icon_path or self.icons is None:
            return None
        key = icon_path.lower()
        if key in self._pil_icon_cache:
            return self._pil_icon_cache[key]
        image = None
        try:
            image = self.icons.get_image(icon_path)
        except Exception:
            image = None
        self._pil_icon_cache[key] = image
        return image
