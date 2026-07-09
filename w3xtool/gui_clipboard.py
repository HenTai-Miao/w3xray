"""Shared right-click copy/paste helpers for Tk widgets."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class ClipboardMixin:
    """Attach compact context menus to text inputs and tables."""

    def _attach_ctx_menu(self, ctk_widget, paste: bool = False, copy_all: bool = False) -> None:
        inner = getattr(ctk_widget, "_entry", None) or getattr(ctk_widget, "_textbox", None) or ctk_widget
        menu = tk.Menu(self, tearoff=0)
        if copy_all:
            menu.add_command(label="复制全部", command=lambda: self._copy_all_text(ctk_widget))
        menu.add_command(label="复制", command=lambda: inner.event_generate("<<Copy>>"))
        if paste:
            menu.add_command(label="粘贴", command=lambda: inner.event_generate("<<Paste>>"))

        def popup(event) -> None:
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

        inner.bind("<Button-3>", popup)

    def _copy_all_text(self, textbox) -> None:
        try:
            text = textbox.get("1.0", "end-1c")
            self.clipboard_clear()
            self.clipboard_append(text)
        except tk.TclError:
            pass

    def _attach_tree_copy(self, tree: ttk.Treeview) -> None:
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="复制", command=lambda: self._copy_tree_row(tree))

        def popup(event) -> None:
            row = tree.identify_row(event.y)
            if row and row not in tree.selection():
                tree.selection_set(row)
                tree.focus(row)
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

        tree.bind("<Button-3>", popup)

    def _copy_tree_row(self, tree: ttk.Treeview) -> None:
        selection = tree.selection()
        if not selection:
            return
        lines = []
        for iid in selection:
            text = str(tree.item(iid, "text")).strip()
            values = [str(value) for value in tree.item(iid, "values") if str(value).strip()]
            parts = ([text] if text else []) + values
            lines.append("\t".join(parts))
        if lines:
            self.clipboard_clear()
            self.clipboard_append("\n".join(lines))
