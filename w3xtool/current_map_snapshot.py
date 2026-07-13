"""Stable private snapshots of current Warcraft III map files."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import ntpath
import os
from pathlib import Path
import stat
import tempfile
import time
from typing import Final, override

from .current_map_snapshot_cleanup import (
    SNAPSHOT_EXTENSIONS,
    cleanup_stale_snapshots,
    create_snapshot_directory,
    remove_owned_directory,
)


_COPY_CHUNK_BYTES: Final = 1024 * 1024
_FILE_OPEN_FLAGS: Final = (
    getattr(os, "O_BINARY", 0)
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOINHERIT", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)
_SOURCE_OPEN_FLAGS: Final = os.O_RDONLY | _FILE_OPEN_FLAGS | getattr(
    os, "O_NONBLOCK", getattr(os, "O_NDELAY", 0)
)
_SNAPSHOT_OPEN_FLAGS: Final = os.O_CREAT | os.O_EXCL | os.O_WRONLY | _FILE_OPEN_FLAGS


type _FileIdentity = tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class CurrentMapSnapshot:
    """One stable map copy and the identity of its source."""

    path: Path
    source_path: Path
    sha256: str
    source_device: int
    source_inode: int
    source_size: int
    source_mtime_ns: int
    _directory_device: int = field(repr=False, compare=False)
    _directory_inode: int = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class CurrentMapSnapshotError(OSError):
    """Failure to create a stable current-map snapshot."""

    path: Path
    reason: str

    @override
    def __str__(self) -> str:
        return f"cannot snapshot current map {self.path}: {self.reason}"


def create_current_map_snapshot(path: str | Path) -> CurrentMapSnapshot:
    """Copy one unchanged regular map file into a private temporary directory."""
    source_path = Path(path).absolute()
    extension = source_path.suffix.casefold()
    if extension not in SNAPSHOT_EXTENSIONS:
        raise CurrentMapSnapshotError(source_path, "invalid map extension")
    source_text = str(source_path)
    if os.name == "nt" and (
        ntpath.isreserved(source_text) or source_text.startswith("\\\\.\\")
    ):
        raise CurrentMapSnapshotError(source_path, "unsafe Windows device path")
    try:
        before_details = os.lstat(source_path)
    except OSError as exc:
        raise CurrentMapSnapshotError(source_path, f"could not inspect source: {exc}") from exc
    if not stat.S_ISREG(before_details.st_mode):
        reason = "source is not a regular file or is a symlink"
        raise CurrentMapSnapshotError(source_path, reason)
    before = _identity(before_details)
    try:
        source_descriptor = os.open(source_path, _SOURCE_OPEN_FLAGS)
    except OSError as exc:
        raise CurrentMapSnapshotError(source_path, f"could not open source: {exc}") from exc

    directory: Path | None = None
    directory_identity: tuple[int, int] | None = None
    try:
        opened_details = os.fstat(source_descriptor)
        if not stat.S_ISREG(opened_details.st_mode) or _identity(opened_details) != before:
            raise CurrentMapSnapshotError(source_path, "source identity changed before open")

        temp_root = Path(os.path.realpath(tempfile.gettempdir()))
        directory, directory_identity = create_snapshot_directory(temp_root)
        snapshot_path = directory / f"current{extension}"
        digest, copied_size = _copy_and_hash(source_descriptor, snapshot_path)

        held_after = _identity(os.fstat(source_descriptor))
        try:
            path_after_details = os.lstat(source_path)
        except OSError as exc:
            raise CurrentMapSnapshotError(source_path, "source changed during copy") from exc
        path_after = _identity(path_after_details)
        if (
            not stat.S_ISREG(path_after_details.st_mode)
            or held_after != before
            or path_after != before
            or copied_size != before[2]
        ):
            raise CurrentMapSnapshotError(source_path, "source changed during copy")
        return CurrentMapSnapshot(
            path=snapshot_path,
            source_path=source_path,
            sha256=digest,
            source_device=before[0],
            source_inode=before[1],
            source_size=before[2],
            source_mtime_ns=before[3],
            _directory_device=directory_identity[0],
            _directory_inode=directory_identity[1],
        )
    except CurrentMapSnapshotError:
        _cleanup_failed_directory(directory, directory_identity)
        raise
    except OSError as exc:
        _cleanup_failed_directory(directory, directory_identity)
        raise CurrentMapSnapshotError(
            source_path,
            f"could not create snapshot: {exc}",
        ) from exc
    finally:
        os.close(source_descriptor)


def cleanup_current_map_snapshot(snapshot: CurrentMapSnapshot) -> None:
    """Remove an owned snapshot directory; repeated calls are harmless."""
    directory_identity = (
        getattr(snapshot, "_directory_device"),
        getattr(snapshot, "_directory_inode"),
    )
    remove_owned_directory(snapshot.path.parent, directory_identity)


def cleanup_stale_current_map_snapshots() -> None:
    """Remove old owned snapshots once, before creating session snapshots."""
    temp_root = Path(os.path.realpath(tempfile.gettempdir()))
    cleanup_stale_snapshots(temp_root, time.time_ns())


def _identity(details: os.stat_result) -> _FileIdentity:
    return details.st_dev, details.st_ino, details.st_size, details.st_mtime_ns


def _copy_and_hash(source_descriptor: int, snapshot_path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    copied_size = 0
    destination_descriptor = os.open(snapshot_path, _SNAPSHOT_OPEN_FLAGS, 0o600)
    with os.fdopen(destination_descriptor, "wb") as destination:
        while chunk := os.read(source_descriptor, _COPY_CHUNK_BYTES):
            digest.update(chunk)
            _ = destination.write(chunk)
            copied_size += len(chunk)
        destination.flush()
        os.fsync(destination.fileno())
    return digest.hexdigest(), copied_size


def _cleanup_failed_directory(
    directory: Path | None,
    identity: tuple[int, int] | None,
) -> None:
    if directory is not None and identity is not None:
        remove_owned_directory(directory, identity)
