"""Exact complete-text view and clipboard controls for object detail."""
# pyright: reportAttributeAccessIssue=false, reportUninitializedInstanceVariable=false

from __future__ import annotations

import customtkinter as ctk

from .object_text_presentation import ObjectTextView, format_complete_text_section
from .theme import ACCENT_DARK, ACCENT_HOVER, FONT, SECONDARY, SECONDARY_HOVER, TEXT


class ObjectTextControlsMixin:
    """Own selected-object text evidence controls outside the detail renderer."""

    def _build_object_text_controls(self, parent) -> None:
        controls = ctk.CTkFrame(parent, fg_color="transparent")
        controls.pack(fill="x", padx=10, pady=(8, 0))
        self.object_text_view = ObjectTextView.ALL
        self.object_text_selector = ctk.CTkSegmentedButton(
            controls,
            values=[item.value for item in ObjectTextView],
            command=self._set_object_text_view,
            selected_color=ACCENT_DARK,
            selected_hover_color=ACCENT_HOVER,
            text_color=TEXT,
        )
        self.object_text_selector.set(ObjectTextView.ALL.value)
        self.object_text_selector.pack(side="left")
        self.copy_complete_text_button = ctk.CTkButton(
            controls,
            text="复制完整文本",
            font=(FONT, 12, "bold"),
            width=112,
            command=self._copy_complete_text,
            fg_color=SECONDARY,
            hover_color=SECONDARY_HOVER,
            text_color=TEXT,
        )
        self.copy_complete_text_button.pack(side="right")
        self._selected_detail_object = None

    def _set_object_text_view(self, value: str) -> None:
        self.object_text_view = ObjectTextView(value)
        self._render_selected_object_detail()

    def _copy_complete_text(self) -> None:
        md = self.map_data
        obj = self._selected_detail_object
        if md is None or obj is None:
            return
        self.clipboard_clear()
        self.clipboard_append(
            format_complete_text_section(md, obj, self.object_text_view)
        )
