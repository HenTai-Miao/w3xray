"""Closed immutable models for retained description-cache integrity evidence."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, unique
from pathlib import Path
from typing import override

from .description_cache_publication_models import RetainedCacheRole


DESCRIPTION_CACHE_RETENTION_SCHEMA = 1


@unique
class CacheArtifactKind(StrEnum):
    """No-follow filesystem kinds visible to the retained scanner."""

    DIRECTORY = "directory"
    REGULAR_FILE = "regular-file"
    SYMLINK = "symlink"
    SPECIAL = "special"
    UNKNOWN = "unknown"


@unique
class RetainedArtifactValidation(StrEnum):
    """The complete retained-artifact validation state."""

    VALID_CACHE = "valid-cache"
    PARTIAL_EVIDENCE = "partial-evidence"
    INVALID_PREVIOUS = "invalid-previous"
    UNSAFE_OBJECT = "unsafe-object"
    OVERSIZED = "oversized"
    UNSTABLE = "unstable"
    UNREADABLE = "unreadable"


@unique
class RetentionArtifactReason(StrEnum):
    """The complete transient or malformed sibling reason."""

    STAGE_TRANSIENT = "stage-transient"
    BACKUP_TRANSIENT = "backup-transient"
    MALFORMED_STAGE_NAME = "malformed-stage-name"
    MALFORMED_BACKUP_NAME = "malformed-backup-name"
    MALFORMED_RETAINED_NAME = "malformed-retained-name"
    UNREADABLE_TRANSIENT = "unreadable-transient"


class DescriptionCacheRetentionError(ValueError):
    """A request, scan boundary, or report violates the integrity contract."""

    __slots__ = ("detail",)

    detail: str

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail

    @override
    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True, slots=True)
class RetainedDescriptionCacheArtifact:
    """One exact retained sibling and its bounded validation evidence."""

    path: Path
    transaction_id: str
    role: RetainedCacheRole
    kind: CacheArtifactKind
    device: int | None
    inode: int | None
    validation: RetainedArtifactValidation
    size: int | None = None
    file_count: int | None = None
    entry_count: int | None = None
    sha256: str | None = None
    problem_path: str | None = None


@dataclass(frozen=True, slots=True)
class TransientDescriptionCacheArtifact:
    """One exact stage or backup sibling that violates quiescence."""

    path: Path
    transaction_id: str | None
    kind: CacheArtifactKind
    device: int | None
    inode: int | None
    reason: RetentionArtifactReason


@dataclass(frozen=True, slots=True)
class MalformedDescriptionCacheArtifact:
    """One publication-prefixed sibling whose name violates its grammar."""

    path: Path
    transaction_id: str | None
    kind: CacheArtifactKind
    device: int | None
    inode: int | None
    reason: RetentionArtifactReason


@dataclass(frozen=True, slots=True)
class DescriptionCacheRetentionReport:
    """One stable two-round view of active and non-active cache siblings."""

    schema: int
    active_root: Path
    active_device: int
    active_inode: int
    retained: tuple[RetainedDescriptionCacheArtifact, ...]
    transient: tuple[TransientDescriptionCacheArtifact, ...]
    malformed: tuple[MalformedDescriptionCacheArtifact, ...]


@dataclass(frozen=True, slots=True)
class SiblingState:
    """One relevant parent entry captured without following its name."""

    name: str
    kind: CacheArtifactKind
    device: int | None
    inode: int | None
    size: int | None
    mtime_ns: int | None
    ctime_ns: int | None
    mode: int | None


@dataclass(frozen=True, slots=True)
class TreeEntryState:
    """One descriptor-relative tree entry and optional file digest."""

    relative_path: str
    kind: CacheArtifactKind
    device: int | None
    inode: int | None
    size: int | None
    mtime_ns: int | None
    ctime_ns: int | None
    mode: int | None
    file_sha256: str | None = None


@unique
class TreeProofStatus(StrEnum):
    """Internal bounded tree-proof outcome."""

    COMPLETE = "complete"
    UNSAFE = "unsafe"
    OVERSIZED = "oversized"
    UNSTABLE = "unstable"
    UNREADABLE = "unreadable"


@dataclass(frozen=True, slots=True)
class RetainedTreeProof:
    """Complete or explicitly incomplete proof for one retained artifact."""

    status: TreeProofStatus
    entries: tuple[TreeEntryState, ...]
    size: int | None
    file_count: int | None
    entry_count: int | None
    sha256: str | None
    problem_path: str | None
    payloads: tuple[tuple[str, bytes], ...] = ()


__all__ = (
    "DESCRIPTION_CACHE_RETENTION_SCHEMA",
    "CacheArtifactKind",
    "DescriptionCacheRetentionError",
    "DescriptionCacheRetentionReport",
    "MalformedDescriptionCacheArtifact",
    "RetainedArtifactValidation",
    "RetainedCacheRole",
    "RetainedDescriptionCacheArtifact",
    "RetentionArtifactReason",
    "TransientDescriptionCacheArtifact",
)
