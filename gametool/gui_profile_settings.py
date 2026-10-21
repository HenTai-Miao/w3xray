"""提取开关设置对话框 (模态) — 类目开关组, 保存到持久化配置。

模式参照 gui_casc_browser.CascBrowserDialog: 自建 CTkToplevel 子类,
master 由调用方 (App) 传入, 避开 mixin 类型不被 tkinter 接受的问题。
"""

from __future__ import annotations

import tkinter as tk
from typing import TYPE_CHECKING

import customtkinter as ctk

from .extraction_profile import (
    ALL_CATEGORIES,
    CATEGORY_OBJECTS,
    ExtractionProfile,
    describe_categories,
    load_profile,
    save_profile,
)
from .theme import BG, BORDER, CARD, FONT, PANEL, SUBTLE, TEXT, TITLE_FONT

if TYPE_CHECKING:
    from collections.abc import Callable


class ExtractionProfileDialog(ctk.CTkToplevel):
    """提取开关设置窗口; 保存后立即生效于下次导出。"""

    def __init__(self, master) -> None:
        super().__init__(master)
        self.title("提取设置")
        self.geometry("520x600")
        self.configure(fg_color=BG)
        self.transient(master)
        self.grab_set()

        profile: ExtractionProfile = load_profile()
        self._vars: dict[str, tk.BooleanVar] = {
            key: tk.BooleanVar(value=profile.allows(key)) for key in ALL_CATEGORIES
        }

        header = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=12)
        header.pack(fill="x", padx=16, pady=(16, 8))
        ctk.CTkLabel(
            header,
            text="提取开关",
            font=(TITLE_FONT, 18, "bold"),
            text_color=TEXT,
        ).pack(anchor="w", padx=14, pady=(10, 2))
        ctk.CTkLabel(
            header,
            text="关闭的类目在下次导出资料包时完全不产出, 加快提取速度。",
            font=(FONT, 12),
            text_color=SUBTLE,
            justify="left",
        ).pack(anchor="w", padx=14, pady=(0, 10))

        list_frame = ctk.CTkFrame(
            self, fg_color=CARD, corner_radius=12, border_width=1, border_color=BORDER
        )
        list_frame.pack(fill="both", expand=True, padx=16, pady=8)

        for key, label in describe_categories():
            row = ctk.CTkFrame(list_frame, fg_color="transparent")
            row.pack(fill="x", padx=12, pady=4)
            ctk.CTkSwitch(
                row,
                text="",
                variable=self._vars[key],
                onvalue=True,
                offvalue=False,
                width=44,
            ).pack(side="left", padx=(4, 10))
            ctk.CTkLabel(
                row, text=label, font=(FONT, 13), text_color=TEXT, justify="left"
            ).pack(side="left", fill="x", expand=True)

        self._status_label = ctk.CTkLabel(
            self, text="", font=(FONT, 12), text_color=SUBTLE
        )
        self._status_label.pack(fill="x", padx=16)

        for var in self._vars.values():
            var.trace_add("write", lambda *_: self._refresh_summary())
        self._refresh_summary()

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(fill="x", padx=16, pady=(4, 16))
        ctk.CTkButton(
            btns,
            text="全选",
            width=76,
            height=32,
            font=(FONT, 12),
            command=lambda: self._set_all(True),
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            btns,
            text="仅对象",
            width=76,
            height=32,
            font=(FONT, 12),
            command=self._objects_only,
        ).pack(side="left")
        ctk.CTkButton(
            btns,
            text="保存",
            width=110,
            height=36,
            font=(FONT, 13, "bold"),
            command=self._on_save,
        ).pack(side="right")

    def _collect(self) -> ExtractionProfile:
        return ExtractionProfile({key: self._vars[key].get() for key in ALL_CATEGORIES})

    def _refresh_summary(self) -> None:
        self._status_label.configure(text="当前: " + self._collect().summary())

    def _set_all(self, value: bool) -> None:
        for var in self._vars.values():
            var.set(value)

    def _objects_only(self) -> None:
        for key in ALL_CATEGORIES:
            self._vars[key].set(key == CATEGORY_OBJECTS)

    def _on_save(self) -> None:
        save_profile(self._collect())
        self.destroy()


def open_extraction_profile_dialog(get_master: Callable[[], object]) -> None:
    """入口: 由 GUI 顶层按钮调用, 传 App 自身 (tk master)。"""
    ExtractionProfileDialog(get_master())
