"""Durability primitives for completed files and directory metadata."""

from __future__ import annotations

import errno
import os
from pathlib import Path
from typing import Final


_WINDOWS_UNSUPPORTED_SYNC_ERRORS: Final = frozenset((errno.EBADF, errno.EINVAL))


def sync_file_descriptor(descriptor: int) -> None:
    """Flush one completed regular file to its backing store."""
    os.fsync(descriptor)


def sync_directory_descriptor(descriptor: int) -> None:
    """Flush directory metadata when the host supports directory fsync."""
    try:
        os.fsync(descriptor)
    except OSError as exc:
        if os.name == "nt" and exc.errno in _WINDOWS_UNSUPPORTED_SYNC_ERRORS:
            return
        raise


def sync_directory(path: Path) -> None:
    """Open and synchronize one directory without following a symlink."""
    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        sync_directory_descriptor(descriptor)
    finally:
        os.close(descriptor)
