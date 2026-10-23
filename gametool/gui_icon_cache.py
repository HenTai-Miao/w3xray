"""Icon image cache shared by gallery rows and the detail panel."""

from __future__ import annotations

from typing import Protocol

import customtkinter as ctk
from PIL import Image, ImageTk


class _IconResolverLike(Protocol):
    """图标 resolver 的最小结构协议: 桌面取图 + 关闭释放 (icons 字段唯一消费面)。"""

    def get_image(self, icon_path: str) -> Image.Image | None: ...

    def close(self) -> None: ...


class IconCacheMixin:
    """Host-injected caches; annotations only, no runtime values."""

    icons: _IconResolverLike | None  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入
    _photo_cache: dict[tuple[str, int, str], object]  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入 (ctk.CTkImage | ImageTk.PhotoImage)
    _pil_icon_cache: dict[tuple[str, int], Image.Image | None]  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入

    def _get_photo(self, icon_path, size=36):
        if not icon_path:
            return None
        key = (icon_path.lower(), size, "ctk")
        if key in self._photo_cache:
            return self._photo_cache[key]
        photo = None
        pil = self._get_icon_pil(icon_path)
        if pil is not None:
            icon = pil.resize((size, size), Image.Resampling.LANCZOS)
            photo = ctk.CTkImage(light_image=icon, dark_image=icon, size=(size, size))
        self._photo_cache[key] = photo
        return photo

    def _get_tree_photo(self, icon_path, size=24):
        if not icon_path:
            return None
        key = (icon_path.lower(), size, "tree")
        if key in self._photo_cache:
            return self._photo_cache[key]
        photo = None
        pil = self._get_icon_pil(icon_path)
        if pil is not None:
            icon = pil.resize((size, size), Image.Resampling.LANCZOS)
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
