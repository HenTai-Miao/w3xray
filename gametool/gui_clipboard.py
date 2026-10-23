"""Shared right-click copy/paste helpers for Tk widgets."""

from __future__ import annotations

from typing import Protocol, cast

import customtkinter as ctk
import tkinter as tk
from tkinter import ttk


class _TextLike(Protocol):
    """多行文本控件面: 取文本 + 剪贴板写入 (CTkTextbox/tk.Text 共有能力)。"""

    def get(self, start: str, end: str) -> str: ...

    def clipboard_clear(self) -> None: ...

    def clipboard_append(self, string: str) -> None: ...


class ClipboardMixin:
    """Attach compact context menus to text inputs and tables."""

    # Misc 基类提供 clipboard_clear/append/tk_popup 等宿主方法; App 组合时由 CTk 实现承载。

    def _attach_ctx_menu(
        self,
        widget: ctk.CTkEntry | ctk.CTkTextbox,
        *,
        paste: bool = False,
        copy_all: bool = False,
    ) -> None:
        inner = (
            getattr(widget, "_entry", None)
            or getattr(widget, "_textbox", None)
            or widget
        )
        menu = tk.Menu(
            cast(tk.Misc, cast(object, self)), tearoff=0
        )  # 运行时 self 是 App (CTk/Misc), mixin 自身无需继承 Misc
        if copy_all:
            menu.add_command(
                label="复制全部",
                command=lambda: self._copy_all_text(cast("_TextLike", inner)),
            )
        menu.add_command(label="复制", command=lambda: inner.event_generate("<<Copy>>"))
        if paste:
            menu.add_command(
                label="粘贴", command=lambda: inner.event_generate("<<Paste>>")
            )

        def popup(event) -> None:
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

        inner.bind("<Button-3>", popup)

    def _copy_all_text(self, textbox: _TextLike) -> None:
        try:
            text = textbox.get("1.0", "end-1c")
            textbox.clipboard_clear()
            textbox.clipboard_append(text)
        except tk.TclError:
            pass

    def _attach_tree_copy(self, tree: ttk.Treeview) -> None:
        menu = tk.Menu(
            cast(tk.Misc, cast(object, self)), tearoff=0
        )  # 运行时 self 是 App (CTk/Misc), mixin 自身无需继承 Misc
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
            values = [
                str(value) for value in tree.item(iid, "values") if str(value).strip()
            ]
            parts = ([text] if text else []) + values
            lines.append("\t".join(parts))
        if lines:
            tree.clipboard_clear()
            tree.clipboard_append("\n".join(lines))
