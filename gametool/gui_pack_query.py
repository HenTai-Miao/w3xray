"""GUI 内直查当前资料包 — search/doc 子命令的图形入口 (后台线程, 结果弹窗)。"""

from __future__ import annotations

import os
import tkinter as tk
from typing import TYPE_CHECKING

import customtkinter as ctk

from .theme import BG, CARD, FONT, SUBTLE, TEXT, TITLE_FONT

if TYPE_CHECKING:
    from collections.abc import Callable


_LAST_KEYWORD = ""
_LAST_MODE = "doc"
_LAST_RESULT = ""


def open_pack_query_dialog(
    master,
    pack_dir_provider: Callable[[], str | None],
    ensure_pack: Callable[[], str | None],
    prefill: str = "",
) -> None:
    """打开包查询窗口。

    pack_dir_provider 返回最近一次导出的资料包目录 (无则 None);
    ensure_pack 在无包时回调 GUI 的导出动作 (先导出再查)。
    """
    pack_dir = pack_dir_provider()
    if not pack_dir or not os.path.isdir(pack_dir):
        ensure_pack()
        return
    _PackQueryWindow(master, pack_dir)


class _PackQueryWindow(ctk.CTkToplevel):
    def __init__(self, master, pack_dir: str) -> None:
        super().__init__(master)
        self.title("资料包查询")
        self.geometry("760x560")
        self.configure(fg_color=BG)
        self.transient(master)
        self.grab_set()
        self._pack_dir = pack_dir

        header = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12)
        header.pack(fill="x", padx=14, pady=(14, 8))
        ctk.CTkLabel(
            header,
            text="资料包查询",
            font=(TITLE_FONT, 17, "bold"),
            text_color=TEXT,
        ).pack(anchor="w", padx=12, pady=(8, 0))
        ctk.CTkLabel(
            header,
            text=f"包: {pack_dir}",
            font=(FONT, 11),
            text_color=SUBTLE,
            anchor="w",
            justify="left",
        ).pack(fill="x", padx=12, pady=(0, 8))

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=14)
        self._keyword = ctk.CTkEntry(row, placeholder_text="四码或名称…", width=280)
        self._keyword.insert(0, prefill or _LAST_KEYWORD)
        self._keyword.pack(side="left", padx=(0, 8))
        self._keyword.bind("<Return>", lambda _e: self._run("doc"))
        self._mode = ctk.CTkSegmentedButton(
            row, values=["doc", "search", "list", "buffs", "export"], width=200
        )
        self._mode.set(_LAST_MODE)
        self._mode.pack(side="left", padx=(0, 8))
        ctk.CTkButton(row, text="查询", width=84, command=self._run_clicked).pack(
            side="left"
        )

        self._output = ctk.CTkTextbox(self, font=("Consolas", 12), wrap="none")
        self._output.pack(fill="both", expand=True, padx=14, pady=10)
        if _LAST_RESULT:
            self._output.insert("1.0", _LAST_RESULT)
        if prefill:
            self.after(120, lambda: self._run("doc"))
        elif not _LAST_RESULT:
            self.after(120, lambda: self._run("stats"))
            self.after(120, lambda: self._run("doc"))

        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="复制全部", command=self._copy_all)
        self._output.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))

    def _run_clicked(self) -> None:
        self._run(self._mode.get())

    def _run(self, command: str) -> None:
        global _LAST_KEYWORD, _LAST_MODE
        _LAST_KEYWORD = self._keyword.get().strip()
        _LAST_MODE = command
        keyword = self._keyword.get().strip()
        if command == "doc" and not keyword:
            self._output.delete("1.0", "end")
            self._output.insert("1.0", "doc 需要四码或名称")
            return
        self._output.delete("1.0", "end")
        self._output.insert("1.0", "查询中 …")
        self.configure(cursor="watch")
        self.after(50, lambda: self._run_blocking(command, keyword))

    def _run_blocking(self, command: str, keyword: str) -> None:
        try:
            from gametool.pack_query_cli import (
                PackQueryCliOptions,
                run_pack_query_cli,
            )
        except ImportError as exc:  # pragma: no cover
            self._finish(f"查询模块不可用: {exc}")
            return
        import contextlib
        import io

        options = PackQueryCliOptions(
            pack_dir=self._pack_dir, command=command, query=keyword, limit=0
        )
        buffer = io.StringIO()
        try:
            with contextlib.redirect_stdout(buffer):
                run_pack_query_cli(options)
            self._finish(buffer.getvalue() or "(无输出)")
        except SystemExit as exc:  # run_pack_query_cli 返回码路径不打异常
            output = buffer.getvalue() or f"(退出码 {exc.code})"
            self._finish(output)

    def _copy_all(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self._output.get("1.0", "end"))

    def _finish(self, text: str) -> None:
        global _LAST_RESULT
        _LAST_RESULT = text
        self.configure(cursor="")
        self._output.delete("1.0", "end")
        self._output.insert("1.0", text)
