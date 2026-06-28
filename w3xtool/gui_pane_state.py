"""Persistent Tk paned-window sash positions."""

from __future__ import annotations

import tkinter as tk
from typing import Final
from tkinter import ttk

from .theme import LAYOUT_VERSION

OBJECT_EDITOR_PANE_KEY: Final = "object_editor"
PANE_SASHES_KEY: Final = "pane_sashes"
LEGACY_OBJECT_SASHES_KEY: Final = "sashes"


class PaneStateMixin:
    """Persist every registered PanedWindow under a stable name."""

    def _init_pane_state(self) -> None:
        self._paned_windows: dict[str, ttk.PanedWindow] = {}

    def _register_paned_window(self, name: str, paned: ttk.PanedWindow) -> None:
        self._paned_windows[name] = paned
        paned.bind("<ButtonRelease-1>", lambda _event: self._save_layout_state(), add="+")

    def _restore_pane_sashes(self) -> None:
        cfg = self._load_config()
        if cfg.get("layout") != LAYOUT_VERSION:
            return
        self.update_idletasks()
        for name, paned in self._paned_windows.items():
            positions = _configured_positions(cfg, name)
            _apply_sash_positions(paned, positions)

    def _save_layout_state(self, *, geometry: str | None = None) -> None:
        pane_sashes = {
            name: positions
            for name, paned in self._paned_windows.items()
            if (positions := _paned_sash_positions(paned))
        }
        payload = {
            "layout": LAYOUT_VERSION,
            PANE_SASHES_KEY: pane_sashes,
        }
        legacy_object_sashes = pane_sashes.get(OBJECT_EDITOR_PANE_KEY)
        if legacy_object_sashes is not None:
            payload[LEGACY_OBJECT_SASHES_KEY] = legacy_object_sashes
        if geometry is not None:
            payload["geometry"] = geometry
        self._save_config(**payload)


def _configured_positions(cfg, name: str) -> list[int]:
    pane_sashes = cfg.get(PANE_SASHES_KEY)
    if isinstance(pane_sashes, dict):
        positions = _int_positions(pane_sashes.get(name))
        if positions:
            return positions
    if name == OBJECT_EDITOR_PANE_KEY:
        return _int_positions(cfg.get(LEGACY_OBJECT_SASHES_KEY))
    return []


def _int_positions(raw) -> list[int]:
    if not isinstance(raw, list):
        return []
    positions: list[int] = []
    for item in raw:
        try:
            positions.append(int(item))
        except (TypeError, ValueError):
            return []
    return positions


def _paned_sash_positions(paned: ttk.PanedWindow) -> list[int]:
    positions: list[int] = []
    for index in range(max(0, len(paned.panes()) - 1)):
        try:
            positions.append(int(paned.sashpos(index)))
        except tk.TclError:
            break
    return positions


def _apply_sash_positions(paned: ttk.PanedWindow, positions: list[int]) -> None:
    for index, position in enumerate(positions):
        try:
            paned.sashpos(index, position)
        except tk.TclError:
            break
