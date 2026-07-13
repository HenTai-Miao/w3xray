"""Ownership validation and bounded cleanup for current-map snapshots."""

from __future__ import annotations

import errno
from itertools import islice
import os
from pathlib import Path
import stat
import tempfile
from typing import Final


SNAPSHOT_EXTENSIONS: Final = frozenset({".w3m", ".w3n", ".w3x"})
SNAPSHOT_DIR_PREFIX: Final = "w3xray-current-map-"
_OWNER_MARKER_NAME: Final = ".w3xray-current-map-owner"
_OWNER_MARKER_CONTENT: Final = b"W3XRAY_CURRENT_MAP_SNAPSHOT_V1\n"
_STALE_AFTER_NS: Final = 24 * 60 * 60 * 1_000_000_000
_MAX_STALE_SCAN_ENTRIES: Final = 64
_MAX_STALE_REMOVALS: Final = 8
_FILE_OPEN_FLAGS: Final = (
    getattr(os, "O_BINARY", 0)
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOINHERIT", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)
_MARKER_READ_FLAGS: Final = os.O_RDONLY | _FILE_OPEN_FLAGS | getattr(
    os, "O_NONBLOCK", getattr(os, "O_NDELAY", 0)
)
_MARKER_CREATE_FLAGS: Final = os.O_CREAT | os.O_EXCL | os.O_WRONLY | _FILE_OPEN_FLAGS


type DirectoryIdentity = tuple[int, int]
type FileIdentity = tuple[int, int, int, int]


def create_snapshot_directory(temp_root: Path) -> tuple[Path, DirectoryIdentity]:
    """Create one private directory with an atomic ownership marker."""
    directory = Path(tempfile.mkdtemp(prefix=SNAPSHOT_DIR_PREFIX, dir=temp_root))
    marker = directory / _OWNER_MARKER_NAME
    marker_created = False
    try:
        os.chmod(directory, 0o700)
        details = os.lstat(directory)
        if not stat.S_ISDIR(details.st_mode) or not _private_to_current_user(details):
            raise OSError(errno.EPERM, "snapshot directory is not private")
        identity = details.st_dev, details.st_ino
        descriptor = os.open(marker, _MARKER_CREATE_FLAGS, 0o600)
        marker_created = True
        with os.fdopen(descriptor, "wb") as marker_file:
            _ = marker_file.write(_OWNER_MARKER_CONTENT)
            marker_file.flush()
            os.fsync(marker_file.fileno())
    except OSError as creation_error:
        try:
            if marker_created:
                marker.unlink(missing_ok=True)
            directory.rmdir()
        except OSError as cleanup_error:
            raise creation_error from cleanup_error
        raise
    return directory, identity


def cleanup_stale_snapshots(temp_root: Path, now_ns: int) -> None:
    """Attempt a bounded cleanup of old, positively owned directories."""
    cutoff_ns = now_ns - _STALE_AFTER_NS
    try:
        entries = os.scandir(temp_root)
    except OSError:
        return
    attempted_removals = 0
    with entries:
        for entry in islice(entries, _MAX_STALE_SCAN_ENTRIES):
            if not entry.name.startswith(SNAPSHOT_DIR_PREFIX):
                continue
            try:
                details = os.lstat(entry.path)
            except OSError:
                continue
            if not stat.S_ISDIR(details.st_mode) or details.st_mtime_ns > cutoff_ns:
                continue
            remove_owned_directory(
                Path(entry.path),
                (details.st_dev, details.st_ino),
            )
            attempted_removals += 1
            if attempted_removals >= _MAX_STALE_REMOVALS:
                break


def remove_owned_directory(directory: Path, expected: DirectoryIdentity) -> None:
    """Remove only a private directory with a validated ownership marker."""
    try:
        details = os.lstat(directory)
    except OSError:
        return
    if (
        not stat.S_ISDIR(details.st_mode)
        or (details.st_dev, details.st_ino) != expected
        or not directory.name.startswith(SNAPSHOT_DIR_PREFIX)
        or not _private_to_current_user(details)
        or not _valid_owner_marker(directory)
    ):
        return
    names = tuple(f"current{extension}" for extension in SNAPSHOT_EXTENSIONS)
    for name in (*names, _OWNER_MARKER_NAME):
        try:
            (directory / name).unlink()
        except FileNotFoundError:
            continue
        except OSError:
            return
    try:
        repeated = os.lstat(directory)
        if (repeated.st_dev, repeated.st_ino) == expected:
            directory.rmdir()
    except OSError:
        return


def _valid_owner_marker(directory: Path) -> bool:
    marker = directory / _OWNER_MARKER_NAME
    try:
        before_details = os.lstat(marker)
        expected = _file_identity(before_details)
        if (
            not stat.S_ISREG(before_details.st_mode)
            or before_details.st_size != len(_OWNER_MARKER_CONTENT)
            or before_details.st_nlink != 1
            or not _private_to_current_user(before_details)
        ):
            return False
        descriptor = os.open(marker, _MARKER_READ_FLAGS)
    except OSError:
        return False
    try:
        opened_details = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened_details.st_mode)
            or _file_identity(opened_details) != expected
            or not _private_to_current_user(opened_details)
        ):
            return False
        content = os.read(descriptor, len(_OWNER_MARKER_CONTENT) + 1)
        held_after = _file_identity(os.fstat(descriptor))
    except OSError:
        return False
    finally:
        os.close(descriptor)
    try:
        path_after = _file_identity(os.lstat(marker))
    except OSError:
        return False
    return content == _OWNER_MARKER_CONTENT and held_after == expected and path_after == expected


def _file_identity(details: os.stat_result) -> FileIdentity:
    return details.st_dev, details.st_ino, details.st_size, details.st_mtime_ns


def _private_to_current_user(details: os.stat_result) -> bool:
    return os.name != "posix" or (
        stat.S_IMODE(details.st_mode) & 0o077 == 0
        and details.st_uid == os.geteuid()
    )
