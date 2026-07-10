"""Paged native CASC browser dialog for the desktop workbench."""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

import customtkinter as ctk

from .casc_browser import CascBrowserModel, CascInventoryPage
from .casclib_enumeration import CascEntry, CascNameType
from .game_data_inventory import GameDataInventorySource, GameDataInventoryView, supports_inventory
from .game_data_source import open_game_data_source
from .theme import FONT, SUBTLE, TEXT, primary_button_style, secondary_button_style


class CascBrowserMixin:
    """Open and own the optional native game-data browser."""

    def on_browse_game_data(self) -> None:
        path = self.game_data_path
        if not path:
            self.status.configure(text="先选择原生 Warcraft III 游戏数据目录")
            return
        self.status.configure(text="正在打开客户端 CASC Root …")

        def open_source() -> None:
            try:
                source = open_game_data_source(path)
            except OSError as exc:
                message = str(exc)
                self.after(0, lambda: self.status.configure(text=f"CASC 打开失败：{message}"))
                return
            if not supports_inventory(source):
                if source is not None:
                    source.close()
                self.after(0, lambda: self.status.configure(text="所选客户端数据不支持资源枚举"))
                return
            self.after(0, lambda: self._show_casc_browser(source))

        threading.Thread(target=open_source, daemon=True).start()

    def _show_casc_browser(self, source: GameDataInventorySource) -> None:
        current = self._casc_browser_dialog
        if current is not None and current.winfo_exists():
            current.close()
        self._casc_browser_dialog = CascBrowserDialog(
            self,
            source,
            listfile=self.external_listfile_path,
        )
        if source.inventory_view is GameDataInventoryView.FULL_ROOT:
            text = "CASC 完整 Root 已打开；未知路径按 FileDataID/CKey/EKey 显示"
        else:
            text = "客户端已知路径已打开；仅显示当前数据源可枚举的逻辑路径"
        self.status.configure(text=text)


class CascBrowserDialog(ctk.CTkToplevel):
    """Browse a large CASC root one bounded page at a time."""

    def __init__(
        self,
        parent,
        source: GameDataInventorySource,
        *,
        listfile: str | None,
    ) -> None:
        super().__init__(parent)
        self.title("CASC 客户端资源浏览")
        self.geometry("1080x680")
        self.minsize(820, 520)
        self.transient(parent)
        self._source = source
        self._model = CascBrowserModel(source, page_size=200)
        self._listfile = listfile
        self._page_number = 0
        self._rows: dict[str, CascEntry] = {}
        self._mask = tk.StringVar(value="*")
        self._build_controls()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(0, self._restart)

    def _build_controls(self) -> None:
        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.pack(fill="x", padx=12, pady=(12, 8))
        ctk.CTkLabel(toolbar, text="路径掩码", font=(FONT, 12), text_color=TEXT).pack(side="left")
        entry = ctk.CTkEntry(toolbar, textvariable=self._mask, width=360, height=32)
        entry.pack(side="left", padx=8)
        entry.bind("<Return>", lambda _event: self._restart())
        ctk.CTkButton(
            toolbar,
            text="搜索/重置",
            width=92,
            height=32,
            command=self._restart,
            **primary_button_style(),
        ).pack(side="left", padx=(0, 6))
        self.next_button = ctk.CTkButton(
            toolbar,
            text="下一页",
            width=72,
            height=32,
            command=self._next_page,
            **secondary_button_style(),
        )
        self.next_button.pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            toolbar,
            text="导出所选",
            width=88,
            height=32,
            command=self._export_selected,
            **secondary_button_style(),
        ).pack(side="left")
        self.status = ctk.CTkLabel(toolbar, text="", font=(FONT, 11), text_color=SUBTLE)
        self.status.pack(side="right")
        columns = ("type", "id", "size", "local", "ckey")
        self.tree = ttk.Treeview(self, columns=columns, show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="路径 / 稳定标识")
        self.tree.heading("type", text="名称类型")
        self.tree.heading("id", text="FileDataID")
        self.tree.heading("size", text="大小")
        self.tree.heading("local", text="本地")
        self.tree.heading("ckey", text="CKey")
        self.tree.column("#0", width=430, minwidth=220)
        self.tree.column("type", width=100, anchor="center")
        self.tree.column("id", width=100, anchor="e")
        self.tree.column("size", width=100, anchor="e")
        self.tree.column("local", width=56, anchor="center")
        self.tree.column("ckey", width=245)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y", pady=(0, 12), padx=(0, 12))
        self.tree.pack(fill="both", expand=True, padx=(12, 0), pady=(0, 12))

    def _restart(self) -> None:
        self._model.reset(mask=self._mask.get().strip() or "*", listfile=self._listfile)
        self._page_number = 0
        self._next_page()

    def _next_page(self) -> None:
        try:
            page = self._model.next_page()
        except OSError as exc:
            messagebox.showerror("CASC 枚举失败", str(exc), parent=self)
            return
        self._page_number += 1
        self._render_page(page)

    def _render_page(self, page: CascInventoryPage) -> None:
        self.tree.delete(*self.tree.get_children())
        self._rows = {}
        for index, entry in enumerate(page.entries):
            iid = f"entry-{self._page_number}-{index}"
            self._rows[iid] = entry
            self.tree.insert(
                "",
                "end",
                iid=iid,
                text=entry.name,
                values=(
                    _name_type_label(entry.name_type),
                    "" if entry.file_data_id is None else entry.file_data_id,
                    "" if entry.size is None else entry.size,
                    "是" if entry.is_local else "否",
                    entry.ckey,
                ),
            )
        self.next_button.configure(state="disabled" if page.is_complete else "normal")
        suffix = " · 已到末尾" if page.is_complete else ""
        self.status.configure(text=f"第 {self._page_number} 页 · {len(page.entries)} 条{suffix}")

    def _export_selected(self) -> None:
        selected = self.tree.selection()
        if not selected:
            self.status.configure(text="先选择一个资源条目")
            return
        output = filedialog.askdirectory(title="选择 CASC 资源导出目录", parent=self)
        if not output:
            return
        entry = self._rows[selected[0]]
        try:
            path = self._model.export_entry(entry, Path(output))
        except OSError as exc:
            messagebox.showerror("导出失败", str(exc), parent=self)
            return
        self.status.configure(text=f"已导出：{path}")

    def close(self) -> None:
        self._model.close()
        self._source.close()
        self.destroy()


def _name_type_label(name_type: CascNameType) -> str:
    labels = {
        CascNameType.FULL: "真实路径",
        CascNameType.FILE_DATA_ID: "FileDataID",
        CascNameType.CKEY: "CKey",
        CascNameType.EKEY: "EKey",
    }
    return labels[name_type]
