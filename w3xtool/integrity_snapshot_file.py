"""Descriptor-relative full-state file hashing for integrity snapshots."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
from typing import Final, override

from .integrity_path_binding import stable_stat
from .integrity_snapshot_models import IntegrityEntry


_FILE_FLAGS: Final = (
    os.O_RDONLY
    | getattr(os, "O_BINARY", 0)
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)
_READ_BYTES: Final = 1024 * 1024


class IntegritySnapshotFileError(OSError):
    """One snapshot leaf was unsafe, unreadable, or changed during hashing."""

    __slots__ = ("path", "reason")

    path: Path
    reason: str

    def __init__(self, path: Path, reason: str) -> None:
        super().__init__(reason)
        self.path = path
        self.reason = reason

    @override
    def __str__(self) -> str:
        return f"{self.path}: {self.reason}"


def snapshot_regular_file(
    parent_descriptor: int,
    name: str,
    relative_path: str,
    display_path: Path,
    expected: os.stat_result,
) -> IntegrityEntry:
    """Hash one anchored regular leaf and re-prove its exact full state."""
    if not stat.S_ISREG(expected.st_mode):
        raise IntegritySnapshotFileError(display_path, "unsafe snapshot object")
    expected_state = stable_stat(expected)
    try:
        descriptor = os.open(name, _FILE_FLAGS, dir_fd=parent_descriptor)
    except OSError as exc:
        raise IntegritySnapshotFileError(display_path, str(exc)) from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or stable_stat(opened) != expected_state:
            raise IntegritySnapshotFileError(
                display_path,
                "file identity changed before hashing",
            )
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, _READ_BYTES):
            digest.update(chunk)
        after = os.fstat(descriptor)
    except IntegritySnapshotFileError:
        raise
    except OSError as exc:
        raise IntegritySnapshotFileError(display_path, str(exc)) from exc
    finally:
        os.close(descriptor)
    try:
        named = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    except OSError as exc:
        raise IntegritySnapshotFileError(display_path, str(exc)) from exc
    if stable_stat(after) != expected_state or stable_stat(named) != expected_state:
        raise IntegritySnapshotFileError(display_path, "file changed while hashing")
    return IntegrityEntry(
        relative_path,
        expected.st_size,
        expected.st_mtime_ns,
        digest.hexdigest(),
    )


__all__ = ("IntegritySnapshotFileError", "snapshot_regular_file")
