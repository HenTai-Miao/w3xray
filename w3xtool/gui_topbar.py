"""Topbar layout for the GUI shell."""

from __future__ import annotations

import customtkinter as ctk

from .theme import (
    ACCENT,
    BORDER,
    FONT,
    PANEL,
    SUBTLE,
    TEXT,
    TITLE_FONT,
    TOPBAR,
    primary_button_style,
    secondary_button_style,
)


def build_topbar(app) -> None:
    """Build the always-visible top command bar."""
    bar = ctk.CTkFrame(app, fg_color=TOPBAR, corner_radius=0, height=64, border_width=1, border_color=BORDER)
    bar.pack(fill="x", side="top")
    bar.pack_propagate(False)
    brand = ctk.CTkFrame(bar, fg_color="transparent")
    brand.pack(side="left", padx=(16, 14), pady=8)
    ctk.CTkLabel(brand, text="W3XRAY", font=(TITLE_FONT, 21, "bold"), text_color=ACCENT).pack(anchor="w")
    ctk.CTkLabel(brand, text="Warcraft III map workbench", font=(FONT, 11), text_color=SUBTLE).pack(anchor="w")
    ctk.CTkButton(
        bar,
        text="打开地图 / 战役",
        font=(FONT, 13, "bold"),
        width=140,
        height=36,
        command=app.on_open,
        **primary_button_style(),
    ).pack(side="left", padx=(0, 12))
    app.map_label = ctk.CTkLabel(
        bar,
        text="未打开",
        font=(FONT, 12),
        text_color=TEXT,
        fg_color=PANEL,
        corner_radius=6,
        height=32,
    )
    app.map_label.pack(side="left", fill="x", expand=True, padx=(0, 12))
    source_tools = ctk.CTkFrame(bar, fg_color="transparent")
    source_tools.pack(side="right", padx=(0, 8))
    _add_source_selector(source_tools, "外部listfile", app.on_pick_external_listfile)
    app.external_listfile_label = _source_label(source_tools, "listfile: 未选")
    app.external_listfile_clear = ctk.CTkButton(
        source_tools,
        text="×",
        width=24,
        height=26,
        font=(FONT, 14),
        command=app.on_clear_external_listfile,
        state="disabled",
        **secondary_button_style(),
    )
    app.external_listfile_clear.pack(side="left", padx=(0, 4))
    _add_source_selector(source_tools, "游戏数据", app.on_pick_game_data_dir)
    app.game_data_label = _source_label(source_tools, "游戏数据: 未选")
    actions = ctk.CTkFrame(bar, fg_color="transparent")
    actions.pack(side="right", padx=(0, 12))
    for text, width, command in (
        ("导出全部", 88, app.on_export_all),
        ("导出脚本", 82, app.on_export_scripts),
        ("导出ID", 70, app.on_export_ids),
        ("资料包", 70, app.on_export_pack),
    ):
        ctk.CTkButton(
            actions,
            text=text,
            font=(FONT, 12),
            width=width,
            height=30,
            command=command,
            **secondary_button_style(),
        ).pack(side="left", padx=3)


def _add_source_selector(parent, text: str, command) -> None:
    ctk.CTkButton(
        parent,
        text=text,
        font=(FONT, 11),
        width=82,
        height=26,
        command=command,
        **secondary_button_style(),
    ).pack(side="left", padx=(0, 3))


def _source_label(parent, text: str):
    label = ctk.CTkLabel(parent, text=text, font=(FONT, 10), text_color=SUBTLE, width=92, anchor="w")
    label.pack(side="left", padx=(0, 6))
    return label
