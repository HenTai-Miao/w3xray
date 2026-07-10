"""Structured, ordered diagnostics from independent extraction components."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .map_data import MapData


class DiagnosticSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ExtractionDiagnostic:
    component: str
    source: str
    stage: str
    severity: DiagnosticSeverity
    message: str
    recoverable: bool


def record_diagnostic(md: MapData, diagnostic: ExtractionDiagnostic) -> None:
    """Append one exact diagnostic once, preserving first-seen order."""
    if diagnostic not in md.diagnostics:
        md.diagnostics.append(diagnostic)
