"""Immutable models for deterministic filesystem integrity snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, unique
from pathlib import Path
from typing import override


INTEGRITY_SNAPSHOT_SCHEMA = 1


@dataclass(frozen=True, slots=True)
class IntegritySnapshotError(ValueError):
    """A snapshot request or serialized snapshot violates its closed contract."""

    detail: str

    @override
    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True, slots=True)
class SnapshotRoot:
    """One explicitly labeled directory requested for snapshotting."""

    label: str
    path: Path


@dataclass(frozen=True, slots=True)
class IntegrityEntry:
    """One stable regular file and its content-plus-metadata proof."""

    relative_path: str
    size: int
    mtime_ns: int
    sha256: str


@dataclass(frozen=True, slots=True)
class IntegrityRoot:
    """One absolute root and its complete ordered file inventory."""

    label: str
    path: str
    entries: tuple[IntegrityEntry, ...]
    total_size: int
    tree_sha256: str


@dataclass(frozen=True, slots=True)
class IntegritySnapshot:
    """Schema-bound integrity evidence for nonoverlapping roots."""

    schema: int
    roots: tuple[IntegrityRoot, ...]


@unique
class IntegrityDifferenceCode(StrEnum):
    """The complete set of expected-versus-actual differences."""

    ROOT_ADDED = "root_added"
    ROOT_REMOVED = "root_removed"
    ROOT_PATH_CHANGED = "root_path_changed"
    FILE_ADDED = "file_added"
    FILE_REMOVED = "file_removed"
    FILE_CHANGED = "file_changed"


@dataclass(frozen=True, slots=True)
class IntegrityDifference:
    """One canonical difference between two valid snapshots."""

    code: IntegrityDifferenceCode
    root_label: str
    relative_path: str


__all__ = (
    "INTEGRITY_SNAPSHOT_SCHEMA",
    "IntegrityDifference",
    "IntegrityDifferenceCode",
    "IntegrityEntry",
    "IntegrityRoot",
    "IntegritySnapshot",
    "IntegritySnapshotError",
    "SnapshotRoot",
)
