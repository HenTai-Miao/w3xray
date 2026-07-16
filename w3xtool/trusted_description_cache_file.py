"""Stable owned-file reads relative to a trusted cache directory fd."""

from __future__ import annotations

import os
from pathlib import Path
import stat
from typing import Final

from .trusted_description_cache_models import TrustedDescriptionCacheError


_READ_CHUNK_BYTES: Final = 1024 * 1024
_FILE_FLAGS: Final = (
    os.O_RDONLY
    | getattr(os, "O_BINARY", 0)
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)
type _FileState = tuple[int, int, int, int, int, int]


def read_owned_regular_file(
    parent_descriptor: int,
    name: str,
    named: os.stat_result,
    root: Path,
    maximum: int,
) -> bytes:
    """Double-read one held regular-file identity and its anchored name."""
    path = root / name
    _require_regular(named, path, maximum)
    descriptor = -1
    try:
        descriptor = os.open(name, _FILE_FLAGS, dir_fd=parent_descriptor)
        opened = os.fstat(descriptor)
        expected = _file_state(named)
        _require_file_state(opened, expected, path, maximum)
        first = _read_once(descriptor, path, maximum)
        _require_file_state(os.fstat(descriptor), expected, path, maximum)
        second = _read_once(descriptor, path, maximum)
        _require_file_state(os.fstat(descriptor), expected, path, maximum)
        anchored = os.stat(
            name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        _require_file_state(anchored, expected, path, maximum)
        if first != second:
            raise TrustedDescriptionCacheError(
                f"owned file changed while reading: {path}"
            )
        return first
    except TrustedDescriptionCacheError:
        raise
    except OSError as exc:
        raise TrustedDescriptionCacheError(
            f"cannot read owned regular file {path}: {exc}"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _read_once(descriptor: int, path: Path, maximum: int) -> bytes:
    _ = os.lseek(descriptor, 0, os.SEEK_SET)
    payload = bytearray()
    while True:
        chunk = os.read(
            descriptor,
            min(_READ_CHUNK_BYTES, maximum + 1 - len(payload)),
        )
        if not chunk:
            return bytes(payload)
        payload.extend(chunk)
        if len(payload) > maximum:
            raise TrustedDescriptionCacheError(
                f"owned file exceeds size limit {maximum}: {path}"
            )


def _require_regular(details: os.stat_result, path: Path, maximum: int) -> None:
    if not stat.S_ISREG(details.st_mode):
        raise TrustedDescriptionCacheError(f"owned path is not a regular file: {path}")
    if details.st_size > maximum:
        raise TrustedDescriptionCacheError(
            f"owned file exceeds size limit {maximum}: {path}"
        )


def _require_file_state(
    details: os.stat_result,
    expected: _FileState,
    path: Path,
    maximum: int,
) -> None:
    _require_regular(details, path, maximum)
    if _file_state(details) != expected:
        raise TrustedDescriptionCacheError(
            f"owned file identity or metadata changed while reading: {path}"
        )


def _file_state(details: os.stat_result) -> _FileState:
    return (
        details.st_dev,
        details.st_ino,
        details.st_size,
        details.st_mtime_ns,
        details.st_ctime_ns,
        details.st_mode,
    )


__all__ = ("read_owned_regular_file",)
