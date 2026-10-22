"""GUI 报告块类型 (breaking the gui_reports <-> report-builder import cycles)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GuiReportBlock:
    title: str
    lines: tuple[str, ...]
    warning_count: int = 0


__all__ = ("GuiReportBlock",)
