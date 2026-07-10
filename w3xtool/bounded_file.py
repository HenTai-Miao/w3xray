"""Single-open, bounded reads for untrusted local regular files."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat
from typing import Final, override


_READ_CHUNK_BYTES: Final = 1024 * 1024


@dataclass(frozen=True, slots=True)
class FileIdentity:
    device: int
    inode: int
    size: int


@dataclass(frozen=True, slots=True)
class BoundedFileError(OSError):
    path: Path
    reason: str

    @override
    def __str__(self) -> str:
        return f"cannot read regular file {self.path}: {self.reason}"


def read_bounded_regular_file(
    path: Path,
    max_bytes: int,
    *,
    expected: FileIdentity | None = None,
) -> tuple[bytes, FileIdentity]:
    """Read one stable regular-file identity without following a final symlink."""
    descriptor, identity = _open_regular_file(path, max_bytes, expected)
    payload = bytearray()
    try:
        while chunk := os.read(descriptor, min(_READ_CHUNK_BYTES, max_bytes + 1 - len(payload))):
            payload.extend(chunk)
            if len(payload) > max_bytes:
                raise BoundedFileError(path, f"size exceeds limit {max_bytes}")
    except OSError as exc:
        if isinstance(exc, BoundedFileError):
            raise
        raise BoundedFileError(path, str(exc)) from exc
    finally:
        os.close(descriptor)
    return bytes(payload), identity


def sha256_regular_file(
    path: Path,
    max_bytes: int | None = None,
) -> tuple[str, FileIdentity]:
    """Hash one stable regular-file identity with an optional byte limit."""
    descriptor, identity = _open_regular_file(path, max_bytes, None)
    digest = hashlib.sha256()
    total = 0
    try:
        while chunk := os.read(descriptor, _READ_CHUNK_BYTES):
            total += len(chunk)
            if max_bytes is not None and total > max_bytes:
                raise BoundedFileError(path, f"size exceeds limit {max_bytes}")
            digest.update(chunk)
    except OSError as exc:
        if isinstance(exc, BoundedFileError):
            raise
        raise BoundedFileError(path, str(exc)) from exc
    finally:
        os.close(descriptor)
    return digest.hexdigest(), identity


def _open_regular_file(
    path: Path,
    max_bytes: int | None,
    expected: FileIdentity | None,
) -> tuple[int, FileIdentity]:
    try:
        before = os.lstat(path)
    except OSError as exc:
        raise BoundedFileError(path, str(exc)) from exc
    if not stat.S_ISREG(before.st_mode):
        raise BoundedFileError(path, "path is not a regular file or is a symlink")
    if max_bytes is not None and before.st_size > max_bytes:
        raise BoundedFileError(path, f"size exceeds limit {max_bytes}")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise BoundedFileError(path, str(exc)) from exc
    try:
        opened = os.fstat(descriptor)
        identity = FileIdentity(opened.st_dev, opened.st_ino, opened.st_size)
        before_identity = FileIdentity(before.st_dev, before.st_ino, before.st_size)
        if not stat.S_ISREG(opened.st_mode) or identity != before_identity:
            raise BoundedFileError(path, "file identity changed before open")
        if expected is not None and identity != expected:
            raise BoundedFileError(path, "file identity changed after validation")
        if max_bytes is not None and identity.size > max_bytes:
            raise BoundedFileError(path, f"size exceeds limit {max_bytes}")
    except (OSError, BoundedFileError):
        os.close(descriptor)
        raise
    return descriptor, identity
