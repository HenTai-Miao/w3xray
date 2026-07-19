"""Typed stage dispositions for integrity-report publication."""

from __future__ import annotations

from dataclasses import dataclass

from .safe_output_models import SafeWriteResult


@dataclass(frozen=True, slots=True)
class IntegrityPublicationComplete:
    """Publication consumed or already handled the staged report name."""

    result: SafeWriteResult | None


@dataclass(frozen=True, slots=True)
class IntegrityStageCleanupRequired:
    """Publication failed before exchange; identity-gated cleanup is safe."""

    result: SafeWriteResult


@dataclass(frozen=True, slots=True)
class IntegrityStageRetained:
    """Exchange state is uncertain; the staged name must remain untouched."""

    result: SafeWriteResult


type IntegrityPublicationOutcome = (
    IntegrityPublicationComplete
    | IntegrityStageCleanupRequired
    | IntegrityStageRetained
)


__all__ = (
    "IntegrityPublicationComplete",
    "IntegrityPublicationOutcome",
    "IntegrityStageCleanupRequired",
    "IntegrityStageRetained",
)
