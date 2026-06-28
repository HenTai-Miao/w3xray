"""编辑器式总览与分析报告 GUI 面板。"""
from __future__ import annotations

from typing import TYPE_CHECKING

import customtkinter as ctk

from .theme import (
    ACCENT_DARK,
    ACCENT_HOVER,
    BG,
    BORDER,
    CARD,
    CARD_RAISED,
    FONT,
    INFO,
    MUTED,
    PANEL,
    SECONDARY,
    SECONDARY_HOVER,
    SUBTLE,
    TEXT,
    TEXT_STRONG,
    TITLE_FONT,
)

if TYPE_CHECKING:
    from .gui_reports import GuiReportBlock


class ReportTabsMixin:
    """为主窗口提供总览与分析报告两个只读面板。"""

    def _build_overview_tab(self, parent) -> None:
        self.overview_box = self._build_hidden_report_cache(parent)
        self.overview_cards: list[ctk.CTkFrame] = []
        self.overview_surface = self._build_report_surface(
            parent,
            title="地图总览",
            subtitle="对象、脚本、场景和风险快照",
            copy_command=lambda: self._copy_report_text(self.overview_box),
        )

    def _build_analysis_tab(self, parent) -> None:
        self.analysis_box = self._build_hidden_report_cache(parent)
        self.analysis_cards: list[ctk.CTkFrame] = []
        self.analysis_surface = self._build_report_surface(
            parent,
            title="分析报告",
            subtitle="审计、兼容、资源、命令、崩溃与调试口令",
            copy_command=lambda: self._copy_report_text(self.analysis_box),
        )

    def _build_hidden_report_cache(self, parent) -> ctk.CTkTextbox:
        textbox = ctk.CTkTextbox(
            parent,
            width=1,
            height=1,
            font=(FONT, 12),
            fg_color=PANEL,
            text_color=TEXT,
            border_width=0,
            wrap="word",
        )
        textbox.configure(state="disabled")
        return textbox

    def _build_report_surface(self, parent, *, title: str, subtitle: str, copy_command):
        shell = ctk.CTkFrame(parent, fg_color=BG)
        shell.pack(fill="both", expand=True, padx=8, pady=8)

        head = ctk.CTkFrame(shell, fg_color=CARD, corner_radius=16,
                            border_width=1, border_color=BORDER, height=62)
        head.pack(fill="x", padx=2, pady=(0, 8))
        head.pack_propagate(False)
        title_group = ctk.CTkFrame(head, fg_color="transparent")
        title_group.pack(side="left", fill="both", expand=True, padx=16, pady=8)
        ctk.CTkLabel(title_group, text=title, font=(TITLE_FONT, 18, "bold"),
                     text_color=TEXT_STRONG, anchor="w").pack(fill="x")
        ctk.CTkLabel(title_group, text=subtitle, font=(FONT, 12),
                     text_color=SUBTLE, anchor="w").pack(fill="x", pady=(2, 0))
        ctk.CTkButton(head, text="复制全文", width=86, height=32, font=(FONT, 12, "bold"),
                      fg_color=SECONDARY, hover_color=SECONDARY_HOVER,
                      text_color=TEXT, corner_radius=14,
                      command=copy_command).pack(side="right", padx=14)

        surface = ctk.CTkScrollableFrame(
            shell,
            fg_color=BG,
            scrollbar_fg_color=BG,
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=ACCENT_HOVER,
        )
        surface.pack(fill="both", expand=True)
        return surface

    def _copy_report_text(self, textbox) -> None:
        text = textbox.get("1.0", "end").strip()
        self.clipboard_clear()
        self.clipboard_append(text)

    def _set_textbox(self, textbox, text: str) -> None:
        textbox.configure(state="normal")
        textbox.delete("1.0", "end")
        textbox.insert("end", text)
        textbox.configure(state="disabled")

    def _refresh_editor_reports(self) -> None:
        if not hasattr(self, "overview_box") or not hasattr(self, "analysis_box"):
            return
        if not self.map_data:
            overview_empty = "打开地图后，这里会显示对象、脚本、场景和风险快照。"
            analysis_empty = "打开地图后，这里会汇总审计、兼容、资源、命令、崩溃与秘籍风险。"
            self._set_textbox(self.overview_box, overview_empty)
            self._set_textbox(self.analysis_box, analysis_empty)
            self._render_empty_report(self.overview_surface, self.overview_cards, overview_empty)
            self._render_empty_report(self.analysis_surface, self.analysis_cards, analysis_empty)
            return

        from w3xtool.gui_reports import build_analysis_blocks, build_overview_blocks, format_blocks

        overview = build_overview_blocks(
            self.map_data,
            command_count=len(self.commands),
            recipe_count=len(self.recipes),
        )
        analysis = build_analysis_blocks(self.map_data)
        self._set_textbox(self.overview_box, format_blocks(overview))
        self._set_textbox(self.analysis_box, format_blocks(analysis))
        self._render_report_cards(self.overview_surface, self.overview_cards, overview, compact=True)
        self._render_report_cards(self.analysis_surface, self.analysis_cards, analysis, compact=False)

    def _render_empty_report(self, surface, cards: list[ctk.CTkFrame], message: str) -> None:
        self._clear_report_cards(surface, cards)
        card = self._make_report_card(surface, "等待地图", (message,), warning_count=0, compact=False)
        card.grid(row=0, column=0, sticky="ew", padx=4, pady=4)
        surface.grid_columnconfigure(0, weight=1)
        cards.append(card)

    def _render_report_cards(
        self,
        surface,
        cards: list[ctk.CTkFrame],
        blocks: tuple["GuiReportBlock", ...],
        *,
        compact: bool,
    ) -> None:
        self._clear_report_cards(surface, cards)
        if not blocks:
            self._render_empty_report(surface, cards, "未发现可展示的报告项。")
            return
        columns = 2 if compact else 1
        for column in range(columns):
            surface.grid_columnconfigure(column, weight=1, uniform="report")
        for index, block in enumerate(blocks):
            row = index // columns
            column = index % columns
            card = self._make_report_card(
                surface,
                block.title,
                block.lines,
                warning_count=block.warning_count,
                compact=compact,
            )
            card.grid(row=row, column=column, sticky="nsew", padx=4, pady=4)
            cards.append(card)

    def _clear_report_cards(self, surface, cards: list[ctk.CTkFrame]) -> None:
        for child in surface.winfo_children():
            child.destroy()
        cards.clear()

    def _make_report_card(
        self,
        parent,
        title: str,
        lines: tuple[str, ...],
        *,
        warning_count: int,
        compact: bool,
    ) -> ctk.CTkFrame:
        has_warning = warning_count > 0
        border = ACCENT_DARK if has_warning else BORDER
        card = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=14,
                            border_width=1, border_color=border)
        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", padx=14, pady=(12, 4))
        ctk.CTkLabel(header, text=title, font=(FONT, 14, "bold"),
                     text_color=TEXT_STRONG, anchor="w").pack(side="left", fill="x", expand=True)
        badge_text = f"警告 {warning_count}" if has_warning else "正常"
        badge_color = "#fff0f6" if has_warning else CARD_RAISED
        badge_text_color = ACCENT_DARK if has_warning else INFO
        ctk.CTkLabel(header, text=badge_text, font=(FONT, 11, "bold"),
                     text_color=badge_text_color, fg_color=badge_color,
                     corner_radius=10, padx=8, pady=2).pack(side="right")

        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        shown_lines = lines if lines else ("暂无条目",)
        limit = 5 if compact else 12
        for line in shown_lines[:limit]:
            self._add_report_line(body, line, warning=_is_warning_line(line), compact=compact)
        if len(shown_lines) > limit:
            self._add_report_line(body, f"另有 {len(shown_lines) - limit} 条，复制全文查看。",
                                  warning=False, compact=compact, muted=True)
        return card

    def _add_report_line(
        self,
        parent,
        line: str,
        *,
        warning: bool,
        compact: bool,
        muted: bool = False,
    ) -> None:
        color = ACCENT_DARK if warning else MUTED if muted else TEXT
        prefix = "● " if warning else "• "
        wrap = 560 if compact else 1320
        ctk.CTkLabel(
            parent,
            text=prefix + line,
            font=(FONT, 12),
            text_color=color,
            anchor="w",
            justify="left",
            wraplength=wrap,
        ).pack(fill="x", pady=2)


def _is_warning_line(line: str) -> bool:
    return "[警告]" in line or "风险" in line or "冲突" in line or "未引用素材" in line
