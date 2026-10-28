"""解析 war3map.wts 字符串表，用于还原 TRIGSTR_n 引用。

格式示例：
    STRING 390
    {
    多行文本
    }
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from .extraction_diagnostics import (
    ComponentParseError,
    DiagnosticSeverity,
    DiagnosticTarget,
    ExtractionDiagnostic,
    record_diagnostic,
)
from .script_string_references import trigstr_reference_id
from .wts_models import WtsReport
from .wts_parser import parse_wts_evidence as parse_wts_evidence


class _MapWtsSource(Protocol):
    @property
    def ui_strings(self) -> dict[int, str] | None: ...

    @property
    def scripts(self) -> dict[str, str]: ...


class _WtsTarget(DiagnosticTarget, Protocol):
    @property
    def wts_reports(self) -> dict[str, WtsReport]: ...


def parse_wts(data: bytes) -> dict[int, str]:
    """Compatibility table containing only complete, unambiguous values."""
    return dict(parse_wts_evidence(data).table)


def parse_wts_component(data: bytes) -> dict[int, str]:
    """Strict component API: reject every unresolved source boundary."""
    report = parse_wts_evidence(data)
    _require_complete(report)
    return dict(report.table)


def validate_wts_component(data: bytes, table: dict[int, str]) -> dict[int, str]:
    """Validate source evidence as well as the supplied compatibility table."""
    report = parse_wts_evidence(data)
    _require_complete(report)
    if table != report.table:
        raise ComponentParseError("WTS table differs from confirmed source values")
    return table


def _require_complete(report: WtsReport) -> None:
    failures = [row for row in report.diagnostics if row.blocking]
    if failures:
        if not report.records:
            raise ComponentParseError("missing WTS STRING header")
        raise ComponentParseError(failures[0].message)


def retain_wts_evidence(md: _WtsTarget, report: WtsReport) -> dict[int, str]:
    """Retain full source evidence and publish every parse issue on the map."""
    md.wts_reports[report.source] = report
    for issue in report.diagnostics:
        record_diagnostic(
            md,
            ExtractionDiagnostic(
                component="wts",
                source=report.source,
                stage="parse",
                severity=(
                    DiagnosticSeverity.WARNING
                    if issue.blocking
                    else DiagnosticSeverity.INFO
                ),
                message=(
                    f"{issue.message}; bytes [{issue.byte_start}, {issue.byte_end}); "
                    f"lines {issue.line_start}-{issue.line_end}; "
                    f"records {','.join(map(str, issue.record_ordinals)) or '-'}"
                ),
                recoverable=True,
                exception_type="WtsDiagnostic",
            ),
        )
    return dict(report.table)


def map_wts_table(md: _MapWtsSource) -> dict[int, str]:
    """Return retained byte-parsed WTS values with text as legacy fallback."""
    if md.ui_strings is not None:
        return dict(md.ui_strings)
    raw = md.scripts.get("war3map.wts") or md.scripts.get("war3campaign.wts")
    if not raw:
        return {}
    try:
        return parse_wts(raw.encode("utf-8", "replace"))
    except UnicodeError, ValueError:
        return {}


def resolve(value: int | float | str, wts: Mapping[int, str]) -> int | float | str:
    """把 'TRIGSTR_390' 这类引用换成实际文本；其它原样返回。"""
    if isinstance(value, str) and value.startswith("TRIGSTR_"):
        digits = value[len("TRIGSTR_") :]
        if not digits or not digits.isdecimal():
            return value
        sid = trigstr_reference_id(digits)
        return wts.get(sid, value)
    return value
