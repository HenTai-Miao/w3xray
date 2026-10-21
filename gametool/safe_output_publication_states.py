"""Explicit location states for displaced safe-output publication objects."""

from __future__ import annotations

from dataclasses import dataclass


type FileIdentity = tuple[int, int]


@dataclass(frozen=True, slots=True)
class DisplacedAtStage:
    """A displaced object is still bound at the publication stage name."""

    name: str
    expected: FileIdentity


@dataclass(frozen=True, slots=True)
class DisplacedAtBackup:
    """A displaced object has reached its transaction backup name."""

    name: str
    expected: FileIdentity


@dataclass(frozen=True, slots=True)
class CleanupRetained:
    """An owned object remains inside a proved isolated cleanup directory."""

    directory_name: str
    directory_identity: FileIdentity
    leaf_name: str
    expected: FileIdentity

    @property
    def name(self) -> str:
        """Return the current nested recovery name relative to the parent."""
        return f"{self.directory_name}/{self.leaf_name}"


type DisplacedState = DisplacedAtStage | DisplacedAtBackup | CleanupRetained
type NamedDisplacedState = DisplacedAtStage | DisplacedAtBackup


@dataclass(frozen=True, slots=True)
class BackupClaimOutcome:
    """Successor state and failure from a stage-to-backup claim."""

    state: DisplacedAtStage | DisplacedAtBackup | None
    error: OSError | None


@dataclass(frozen=True, slots=True)
class CleanupOutcome:
    """Result of consuming one named displaced state for cleanup."""

    state: DisplacedState | None
    error: str | None

    @property
    def retained(self) -> CleanupRetained | None:
        """Return the cleanup-retained successor when one was proved."""
        return self.state if isinstance(self.state, CleanupRetained) else None


@dataclass(frozen=True, slots=True)
class DisplacedOutcome:
    """Successor state and diagnostic for a rollback/recovery transition."""

    state: DisplacedState | None
    error: str | None


__all__ = (
    "BackupClaimOutcome",
    "CleanupOutcome",
    "CleanupRetained",
    "DisplacedOutcome",
    "DisplacedAtBackup",
    "DisplacedAtStage",
    "DisplacedState",
    "FileIdentity",
    "NamedDisplacedState",
)
