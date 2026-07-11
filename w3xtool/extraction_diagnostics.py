"""Structured, ordered diagnostics from independent extraction components."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
import struct
from typing import Final, Protocol, TypeVar, override

_T = TypeVar("_T")
_COMPONENT_ERRORS = (KeyError, OSError, UnicodeError, ValueError, IndexError, struct.error)
_MAX_DIAGNOSTICS: Final = 256
_MAX_DIAGNOSTIC_TEXT: Final = 512


@dataclass(frozen=True, slots=True)
class ComponentParseError(ValueError):
    """A readable component body did not produce a valid parser result."""

    detail: str

    @override
    def __str__(self) -> str:
        return self.detail


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
    exception_type: str = ""


class DiagnosticTarget(Protocol):
    @property
    def diagnostics(self) -> list[ExtractionDiagnostic]: ...

    @property
    def diagnostic_keys(self) -> set[ExtractionDiagnostic]: ...


def record_diagnostic(md: DiagnosticTarget, diagnostic: ExtractionDiagnostic) -> None:
    """Append one exact diagnostic once, preserving first-seen order."""
    normalized = ExtractionDiagnostic(
        component=_clean_text(diagnostic.component),
        source=_clean_text(diagnostic.source),
        stage=_clean_text(diagnostic.stage),
        severity=diagnostic.severity,
        message=_clean_text(diagnostic.message),
        recoverable=diagnostic.recoverable,
        exception_type=_clean_text(diagnostic.exception_type),
    )
    if normalized in md.diagnostic_keys or len(md.diagnostics) >= _MAX_DIAGNOSTICS:
        return
    md.diagnostic_keys.add(normalized)
    md.diagnostics.append(normalized)


def record_component_parse_issue(
    md: DiagnosticTarget,
    component: str,
    source: str,
    detail: str,
    *,
    stage: str = "parse",
) -> None:
    """Retain a tolerant parser's partial-result warning."""
    error = ComponentParseError(detail)
    record_diagnostic(
        md,
        ExtractionDiagnostic(
            component=component,
            source=source,
            stage=stage,
            severity=DiagnosticSeverity.WARNING,
            message=f"{type(error).__name__}: {error}",
            recoverable=True,
            exception_type=type(error).__name__,
        ),
    )


def record_component_failure(
    md: DiagnosticTarget,
    component: str,
    source: str,
    error: Exception,
    *,
    stage: str = "read/parse",
    recoverable: bool = True,
) -> None:
    """Retain one expected boundary failure with its concrete exception type."""
    severity = DiagnosticSeverity.WARNING if recoverable else DiagnosticSeverity.ERROR
    record_diagnostic(
        md,
        ExtractionDiagnostic(
            component=component,
            source=source,
            stage=stage,
            severity=severity,
            message=f"{type(error).__name__}: {error}".rstrip(),
            recoverable=recoverable,
            exception_type=type(error).__name__,
        ),
    )


def read_component(
    md: DiagnosticTarget,
    component: str,
    source: str,
    operation: Callable[[], _T],
    recoverable: bool = True,
    *,
    stage: str = "read/parse",
) -> _T | None:
    """Run one component operation and retain an expected failure as a diagnostic."""
    try:
        return operation()
    except _COMPONENT_ERRORS as exc:
        record_component_failure(
            md,
            component,
            source,
            exc,
            stage=stage,
            recoverable=recoverable,
        )
        return None


def require_component_result(value: _T | None, source: str) -> _T:
    """Return a parser result or raise a typed component rejection."""
    if value is None:
        raise ComponentParseError(f"parser rejected {source}")
    return value


def _clean_text(value: str) -> str:
    cleaned = "".join(char if ord(char) >= 0x20 else " " for char in value)
    return cleaned[:_MAX_DIAGNOSTIC_TEXT]
