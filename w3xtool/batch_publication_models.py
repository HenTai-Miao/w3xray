"""Immutable contracts for recoverable per-map publication transactions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class PublicationPhase(StrEnum):
    """Durable phases of one map-directory replacement."""

    BUILDING = "building"
    PREPARED = "prepared"
    BACKUP_READY = "backup_ready"
    DESTINATION_READY = "destination_ready"
    COMMITTED = "committed"


@dataclass(frozen=True, slots=True)
class MapPublicationStage:
    """Private stage plus the source and destination it is allowed to publish."""

    stage: Path
    transaction_id: str
    relative: str
    digest: str


@dataclass(frozen=True, slots=True)
class PublicationTransaction:
    """Strict durable record used to finish or roll back one publication."""

    transaction_id: str
    phase: PublicationPhase
    stage_name: str
    destination_name: str
    backup_name: str
    source_sha256: str
    manifest_sha256: str


@dataclass(frozen=True, slots=True)
class PublicationPaths:
    """Immediate children bound by a parsed transaction record."""

    record: Path
    stage: Path
    destination: Path
    backup: Path


@dataclass(frozen=True, slots=True)
class RecoveryDiagnostic:
    """Stable outcome or safety reason emitted by startup recovery."""

    code: str
    detail: str = ""
    transaction_id: str = ""


class BatchMapPublicationError(OSError):
    """Publication boundary rejected an unsafe or inconsistent operation."""

    __slots__ = ("detail",)

    detail: str

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail

    def __str__(self) -> str:
        return self.detail


class PublicationRecordError(ValueError):
    """A persisted transaction record is malformed or inconsistent."""

    __slots__ = ("detail",)

    detail: str

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail

    def __str__(self) -> str:
        return self.detail
