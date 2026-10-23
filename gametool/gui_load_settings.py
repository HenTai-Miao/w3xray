"""Internal load options for the GUI."""

from __future__ import annotations

import tkinter as tk

from typing import TYPE_CHECKING

from .load_options import (
    default_load_options,
    normalize_load_options,
)


class LoadSettingsMixin:
    """Keep module load switches enabled now that the settings UI is removed."""

    load_options: dict[str, bool] = {}
    load_option_vars: dict[str, tk.BooleanVar] = {}

    if TYPE_CHECKING:
        from collections.abc import Callable
        from .map_data import MapData

        _campaign_path: str | None  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入
        _save_config: Callable[..., None]  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入
        _start_map_switch: Callable[[MapData, str | None], None]  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入
        map_data: MapData | None  # pyright: ignore[reportUninitializedInstanceVariable] - mixin 宿主注入

    def _init_load_options(self) -> None:
        self.load_options = default_load_options()
        self.load_option_vars: dict[str, tk.BooleanVar] = {}

    def _apply_load_options(
        self,
        options: dict[str, bool],
        *,
        persist: bool,
        refresh: bool,
    ) -> None:
        self.load_options = normalize_load_options(options)
        for key, var in getattr(self, "load_option_vars", {}).items():
            var.set(self.load_options.get(key, True))
        if persist:
            self._save_config(load_options=self.load_options)
        if refresh and self.map_data is not None:
            self._start_map_switch(self.map_data, self._campaign_path)

    def _load_option_enabled(self, key: str) -> bool:
        return self.load_options.get(key, True)
