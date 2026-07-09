"""Data report tab layout builders for the main GUI."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import customtkinter as ctk

from .theme import (
    ACCENT,
    BG,
    BORDER,
    CARD,
    FONT,
    INFO,
    MONO_FONT,
    PANEL,
    SUBTLE,
    TEXT,
    card_style,
    entry_style,
)


class DataTabLayoutMixin:
    """Build the read-only data tabs below the editor workspace."""

    def _build_cmd_tab(self, parent) -> None:
        top = ctk.CTkFrame(parent, fg_color=BG)
        top.pack(fill="x", padx=2, pady=(8, 6))
        self.cmd_search = tk.StringVar()
        entry = ctk.CTkEntry(
            top, textvariable=self.cmd_search, height=40, font=(FONT, 13),
            justify="center", placeholder_text='回车搜索：指令 / 说明    %词%=包含    ="…"=精准',
            **entry_style())
        entry.pack(fill="x")
        entry.bind("<Return>", lambda *_: self._refresh_cmds())
        self._attach_ctx_menu(entry, paste=True)
        self.cmd_hint = ctk.CTkLabel(
            parent, text="打开地图后这里列出脚本里的全部聊天指令（含隐藏指令）",
            font=(FONT, 12), text_color=SUBTLE, anchor="w")
        self.cmd_hint.pack(fill="x", padx=6, pady=(0, 6))
        self.cmd_tree = _build_tree_panel(
            self, parent,
            columns=(("cmd", "指令", 180, "w"), ("match", "匹配", 70, "center"),
                     ("hint", "说明(脚本提示)", 420, "w")),
        )

    def _build_rec_tab(self, parent) -> None:
        top = ctk.CTkFrame(parent, fg_color=BG)
        top.pack(fill="x", padx=2, pady=(8, 6))
        self.rec_search = tk.StringVar()
        entry = ctk.CTkEntry(
            top, textvariable=self.rec_search, height=40, font=(FONT, 13),
            justify="center", placeholder_text='回车搜索：材料 / 成品名称    %词%=包含    ="…"=精准',
            **entry_style())
        entry.pack(fill="x")
        entry.bind("<Return>", lambda *_: self._refresh_recipes())
        self._attach_ctx_menu(entry, paste=True)
        self.rec_hint = ctk.CTkLabel(
            parent, text="打开地图后这里列出脚本里识别到的物品合成配方",
            font=(FONT, 12), text_color=SUBTLE, anchor="w")
        self.rec_hint.pack(fill="x", padx=6, pady=(0, 6))
        self.rec_tree = _build_tree_panel(
            self, parent,
            columns=(("result", "成品", 220, "w"), ("ingredients", "材料（合成所需）", 620, "w")),
        )

    def _build_orphan_tab(self, parent) -> None:
        top = ctk.CTkFrame(parent, fg_color=BG)
        top.pack(fill="x", padx=2, pady=(8, 6))
        self.orphan_search = tk.StringVar()
        entry = ctk.CTkEntry(
            top, textvariable=self.orphan_search, height=40, font=(FONT, 13),
            justify="center", placeholder_text='回车搜索：名称 / ID / 分类    %词%=包含    ="…"=精准',
            **entry_style())
        entry.pack(fill="x")
        entry.bind("<Return>", lambda *_: self._refresh_orphans())
        self._attach_ctx_menu(entry, paste=True)
        self.orphan_hint = ctk.CTkLabel(
            parent, text="打开地图后这里列出「孤立」自定义对象——定义了但没被任何对象/脚本/预放置引用的废弃对象",
            font=(FONT, 12), text_color=SUBTLE, anchor="w")
        self.orphan_hint.pack(fill="x", padx=6, pady=(0, 6))
        self.orphan_tree = _build_tree_panel(
            self, parent,
            columns=(("cat", "分类", 90, "center"), ("id", "ID", 80, "center"),
                     ("name", "名称", 480, "w")),
        )

    def _build_info_tab(self, parent) -> None:
        self.info_box = ctk.CTkTextbox(
            parent, font=(MONO_FONT, 13), fg_color=PANEL, text_color=TEXT,
            border_width=1, border_color=BORDER, wrap="word")
        self.info_box.pack(fill="both", expand=True, padx=4, pady=8)
        self.info_box.configure(state="disabled")
        self._attach_ctx_menu(self.info_box, copy_all=True)

    def _build_preplaced_tab(self, parent) -> None:
        top = ctk.CTkFrame(parent, fg_color=BG)
        top.pack(fill="x", padx=2, pady=(8, 6))
        self.pre_search = tk.StringVar()
        entry = ctk.CTkEntry(
            top, textvariable=self.pre_search, height=40, font=(FONT, 13),
            justify="center", placeholder_text='回车搜索：类型名 / ID    %词%=包含    ="…"=精准',
            **entry_style())
        entry.pack(fill="x")
        entry.bind("<Return>", lambda *_: self._refresh_preplaced())
        self._attach_ctx_menu(entry, paste=True)
        self.pre_hint = ctk.CTkLabel(
            parent, text="打开地图后这里列出地图上预放置的单位与装饰物（摆在哪、归谁、初始属性）",
            font=(FONT, 12), text_color=SUBTLE, anchor="w")
        self.pre_hint.pack(fill="x", padx=6, pady=(0, 6))
        self.unit_title = _section_title(parent, "预放置单位", INFO)
        self.unit_tree = _build_tree_panel(
            self, parent,
            columns=(("name", "类型", 220, "w"), ("id", "ID", 60, "center"),
                     ("player", "玩家", 50, "center"), ("pos", "坐标(x, y)", 150, "center"),
                     ("hp", "生命", 70, "center"), ("mana", "魔法", 70, "center"),
                     ("lv", "等级", 50, "center")),
            pady=(0, 6),
        )
        self.doodad_title = _section_title(parent, "装饰物 / 可破坏物", ACCENT)
        self.doodad_tree = _build_tree_panel(
            self, parent,
            columns=(("name", "类型", 220, "w"), ("id", "ID", 60, "center"),
                     ("pos", "坐标(x, y)", 150, "center"), ("scale", "缩放", 70, "center"),
                     ("life", "生命%", 60, "center"), ("drops", "掉落", 200, "w")),
            pady=(0, 6),
        )


def _section_title(parent, text: str, color: str):
    label = ctk.CTkLabel(parent, text=text, font=(FONT, 12, "bold"), text_color=color, anchor="w")
    label.pack(fill="x", padx=8)
    return label


def _build_tree_panel(owner, parent, *, columns, pady=8):
    wrap = ctk.CTkFrame(parent, **card_style())
    wrap.pack(fill="both", expand=True, padx=4, pady=pady)
    inner = tk.Frame(wrap, bg=CARD)
    inner.pack(fill="both", expand=True, padx=8, pady=8)
    tree = ttk.Treeview(inner, columns=tuple(col[0] for col in columns),
                        show="headings", selectmode="browse")
    for name, title, width, anchor in columns:
        tree.heading(name, text=title)
        tree.column(name, width=width, anchor=anchor, stretch=False)
    vsb = ttk.Scrollbar(inner, orient="vertical", command=tree.yview)
    hsb = ttk.Scrollbar(inner, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
    vsb.pack(side="right", fill="y")
    hsb.pack(side="bottom", fill="x")
    tree.pack(side="left", fill="both", expand=True)
    owner._attach_tree_copy(tree)
    return tree
