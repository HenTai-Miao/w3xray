"""Load-settings tab for the GUI."""

from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from .load_options import (
    LOAD_OPTION_SPECS,
    default_load_options,
    load_options_from_config,
    normalize_load_options,
    object_only_load_options,
)
from .theme import BORDER, CARD, CARD_RAISED, FONT, PANEL, SECONDARY, TEXT, TEXT_STRONG, TITLE_FONT


class LoadSettingsMixin:
    """Persist and edit per-module load switches."""

    def _init_load_options(self) -> None:
        self.load_options = load_options_from_config(self._load_config())
        self.load_option_vars: dict[str, tk.BooleanVar] = {}

    def _build_load_settings_tab(self, parent) -> None:
        shell = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=18,
                             border_width=1, border_color=BORDER)
        shell.pack(fill="both", expand=True, padx=8, pady=8)
        head = ctk.CTkFrame(shell, fg_color="transparent")
        head.pack(fill="x", padx=16, pady=(14, 8))
        ctk.CTkLabel(head, text="加载设置", font=(TITLE_FONT, 18, "bold"),
                     text_color=TEXT_STRONG, anchor="w").pack(side="left", fill="x", expand=True)
        ctk.CTkButton(head, text="全部打开", width=84, height=30, font=(FONT, 12, "bold"),
                      fg_color=SECONDARY, text_color=TEXT, corner_radius=14,
                      command=lambda: self._apply_load_options(
                          default_load_options(), persist=True, refresh=True)
                      ).pack(side="right", padx=(8, 0))
        ctk.CTkButton(head, text="只看对象", width=84, height=30, font=(FONT, 12, "bold"),
                      fg_color=SECONDARY, text_color=TEXT, corner_radius=14,
                      command=lambda: self._apply_load_options(
                          object_only_load_options(), persist=True, refresh=True)
                      ).pack(side="right")

        grid = ctk.CTkFrame(shell, fg_color="transparent")
        grid.pack(fill="x", padx=12, pady=(0, 12))
        for index, spec in enumerate(LOAD_OPTION_SPECS):
            card = ctk.CTkFrame(grid, fg_color=PANEL if index % 2 else CARD_RAISED,
                                corner_radius=14, border_width=1, border_color=BORDER)
            card.grid(row=index // 2, column=index % 2, sticky="ew", padx=5, pady=5)
            grid.grid_columnconfigure(index % 2, weight=1, uniform="load_settings")
            var = tk.BooleanVar(value=self.load_options.get(spec.key, True))
            self.load_option_vars[spec.key] = var
            ctk.CTkCheckBox(
                card,
                text=spec.label,
                variable=var,
                font=(FONT, 13, "bold"),
                text_color=TEXT_STRONG,
                command=lambda key=spec.key: self._on_load_option_toggle(key),
            ).pack(anchor="w", padx=12, pady=(10, 2))
            ctk.CTkLabel(card, text=spec.description, font=(FONT, 11),
                         text_color=TEXT, anchor="w", justify="left",
                         wraplength=420).pack(fill="x", padx=12, pady=(0, 10))

    def _on_load_option_toggle(self, key: str) -> None:
        next_options = dict(self.load_options)
        next_options[key] = bool(self.load_option_vars[key].get())
        self._apply_load_options(next_options, persist=True, refresh=True)

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
