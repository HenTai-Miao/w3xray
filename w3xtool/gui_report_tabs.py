"""编辑器式总览与分析报告 GUI 面板。"""
from __future__ import annotations

import customtkinter as ctk

FONT = "JetBrains Mono"
PANEL = "#2b2b2b"


class ReportTabsMixin:
    """为主窗口提供总览与分析报告两个只读面板。"""

    def _build_overview_tab(self, parent):
        self.overview_box = ctk.CTkTextbox(parent, font=(FONT, 13), fg_color=PANEL, wrap="word")
        self.overview_box.pack(fill="both", expand=True, padx=10, pady=10)
        self.overview_box.configure(state="disabled")
        self._attach_ctx_menu(self.overview_box, copy_all=True)

    def _build_analysis_tab(self, parent):
        self.analysis_box = ctk.CTkTextbox(parent, font=(FONT, 12), fg_color=PANEL, wrap="word")
        self.analysis_box.pack(fill="both", expand=True, padx=10, pady=10)
        self.analysis_box.configure(state="disabled")
        self._attach_ctx_menu(self.analysis_box, copy_all=True)

    def _set_textbox(self, textbox, text):
        textbox.configure(state="normal")
        textbox.delete("1.0", "end")
        textbox.insert("end", text)
        textbox.configure(state="disabled")

    def _refresh_editor_reports(self):
        if not hasattr(self, "overview_box") or not hasattr(self, "analysis_box"):
            return
        if not self.map_data:
            self._set_textbox(self.overview_box, "打开地图后，这里会显示对象、脚本、场景和风险快照。")
            self._set_textbox(self.analysis_box, "打开地图后，这里会汇总审计、兼容、资源、命令、崩溃与秘籍风险。")
            return
        from w3xtool.gui_reports import build_analysis_blocks, build_overview_blocks, format_blocks

        overview = build_overview_blocks(
            self.map_data, command_count=len(self.commands), recipe_count=len(self.recipes))
        analysis = build_analysis_blocks(self.map_data)
        self._set_textbox(self.overview_box, format_blocks(overview))
        self._set_textbox(self.analysis_box, format_blocks(analysis))
