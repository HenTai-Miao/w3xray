"""Widget layout for the item-relation inspection workspace."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Final

import customtkinter as ctk

from .item_relation_models import ItemRelation, ItemRelationKind, RelationConfidence
from .theme import (
    BG,
    BORDER,
    CARD,
    FONT,
    MONO_FONT,
    PANEL,
    SUBTLE,
    TEXT,
    card_style,
    entry_style,
    secondary_button_style,
)

ALL_RELATIONS_LABEL: Final = "全部"
_COLUMNS: Final = (
    ("kind", "关系类型", 130),
    ("item", "装备", 200),
    ("source", "来源 / 技能", 210),
    ("context", "概率 / 玩家 / 坐标", 210),
    ("confidence", "可信度", 80),
    ("complete", "完整性", 80),
    ("evidence", "证据", 280),
)


class ItemRelationLayoutMixin:
    """Build the dense relation ledger and complete evidence pane."""

    def _build_item_relation_tab(self, parent) -> None:
        controls = ctk.CTkFrame(parent, fg_color=BG)
        controls.pack(fill="x", padx=2, pady=(8, 6))
        self.item_relation_search = tk.StringVar()
        search = ctk.CTkEntry(
            controls,
            textvariable=self.item_relation_search,
            height=38,
            font=(FONT, 13),
            placeholder_text="搜索装备、来源、技能、关系 ID 或原始证据",
            **entry_style(),
        )
        search.pack(side="left", fill="x", expand=True, padx=(0, 6))
        search.bind("<Return>", lambda *_: self._refresh_item_relations())
        self._attach_ctx_menu(search, paste=True)
        self.item_relation_kind = ctk.CTkComboBox(
            controls,
            values=(
                ALL_RELATIONS_LABEL,
                *(kind.value for kind in ItemRelationKind),
            ),
            width=150,
            height=38,
            state="readonly",
            command=lambda _value: self._refresh_item_relations(),
        )
        self.item_relation_kind.set(ALL_RELATIONS_LABEL)
        self.item_relation_kind.pack(side="left", padx=(0, 6))
        self.item_relation_confidence = ctk.CTkComboBox(
            controls,
            values=(
                ALL_RELATIONS_LABEL,
                *(value.value for value in RelationConfidence),
            ),
            width=110,
            height=38,
            state="readonly",
            command=lambda _value: self._refresh_item_relations(),
        )
        self.item_relation_confidence.set(ALL_RELATIONS_LABEL)
        self.item_relation_confidence.pack(side="left")
        self.item_relation_status = ctk.CTkLabel(
            parent,
            text="打开地图后这里列出装备掉落、获取方式与装备技能",
            font=(FONT, 12),
            text_color=SUBTLE,
            anchor="w",
        )
        self.item_relation_status.pack(fill="x", padx=6, pady=(0, 6))
        self._build_item_relation_tree(parent)
        self._build_item_relation_evidence(parent)
        self.item_relation_rows: dict[str, ItemRelation] = {}

    def _build_item_relation_tree(self, parent) -> None:
        tree_frame = ctk.CTkFrame(parent, **card_style())
        tree_frame.pack(fill="both", expand=True, padx=4, pady=(0, 6))
        tree_inner = tk.Frame(tree_frame, bg=CARD)
        tree_inner.pack(fill="both", expand=True, padx=8, pady=8)
        self.item_relation_tree = ttk.Treeview(
            tree_inner,
            columns=tuple(column[0] for column in _COLUMNS),
            show="headings",
            selectmode="browse",
        )
        for name, title, width in _COLUMNS:
            self.item_relation_tree.heading(name, text=title)
            self.item_relation_tree.column(name, width=width, anchor="w", stretch=False)
        vsb = ttk.Scrollbar(
            tree_inner,
            orient="vertical",
            command=self.item_relation_tree.yview,
        )
        hsb = ttk.Scrollbar(
            tree_inner,
            orient="horizontal",
            command=self.item_relation_tree.xview,
        )
        self.item_relation_tree.configure(
            yscrollcommand=vsb.set,
            xscrollcommand=hsb.set,
        )
        vsb.pack(side="right", fill="y")
        hsb.pack(side="bottom", fill="x")
        self.item_relation_tree.pack(side="left", fill="both", expand=True)
        self.item_relation_tree.bind(
            "<<TreeviewSelect>>",
            self._show_relation_evidence,
        )
        self.item_relation_tree.bind(
            "<Double-1>",
            lambda _event: self._open_relation_target(),
        )
        self._attach_tree_copy(self.item_relation_tree)

    def _build_item_relation_evidence(self, parent) -> None:
        evidence = ctk.CTkFrame(parent, **card_style())
        evidence.pack(fill="x", padx=4, pady=(0, 8))
        actions = ctk.CTkFrame(evidence, fg_color="transparent")
        actions.pack(fill="x", padx=8, pady=(8, 0))
        self.item_relation_target_button = ctk.CTkButton(
            actions,
            text="打开装备",
            width=96,
            state="disabled",
            command=self._open_relation_target,
            **secondary_button_style(),
        )
        self.item_relation_target_button.pack(side="left")
        self.item_relation_source_button = ctk.CTkButton(
            actions,
            text="打开来源 / 技能",
            width=126,
            state="disabled",
            command=self._open_relation_source,
            **secondary_button_style(),
        )
        self.item_relation_source_button.pack(side="left", padx=(6, 0))
        self.item_relation_detail = ctk.CTkTextbox(
            evidence,
            height=180,
            font=(MONO_FONT, 12),
            fg_color=PANEL,
            text_color=TEXT,
            border_width=1,
            border_color=BORDER,
            wrap="word",
        )
        self.item_relation_detail.pack(fill="x", padx=8, pady=8)
        self.item_relation_detail.configure(state="disabled")
        self._attach_ctx_menu(self.item_relation_detail, copy_all=True)
