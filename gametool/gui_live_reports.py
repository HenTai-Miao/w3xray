"""Explicit offline report actions for the live GUI; no probe imports."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path


def save_report(path: str, report: Mapping[str, object]) -> Path:
    from .live_report import write_live_report

    return write_live_report(path, report)


def open_report(path: str) -> tuple[Mapping[str, object], str]:
    from .live_report import read_live_report

    report = read_live_report(path)
    return report, report.to_json()


def compare_report(path: str, current: Mapping[str, object]) -> str:
    from .live_report import (
        compare_live_reports,
        format_live_report_diff,
        read_live_report,
    )

    old = read_live_report(path)
    return format_live_report_diff(compare_live_reports(old, current))
