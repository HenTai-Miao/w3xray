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
    max_bytes: int | None = None,
    *,
    expected: FileIdentity | None = None,
) -> tuple[bytes, FileIdentity]:
    """Read one stable regular-file identity without following a final symlink."""
    descriptor, identity, named_before = _open_regular_file(path, max_bytes, expected)
    payload = bytearray()
    try:
        before = os.fstat(descriptor)
        ceiling = identity.size if max_bytes is None else min(identity.size, max_bytes)
        while chunk := os.read(
            descriptor, min(_READ_CHUNK_BYTES, ceiling + 1 - len(payload))
        ):
            payload.extend(chunk)
            if max_bytes is not None and len(payload) > max_bytes:
                raise BoundedFileError(path, f"size exceeds limit {max_bytes}")
            if len(payload) > identity.size:
                raise BoundedFileError(path, "file grew while reading")
        _require_unchanged(path, descriptor, before, named_before, len(payload))
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
    descriptor, identity, named_before = _open_regular_file(path, max_bytes, None)
    digest = hashlib.sha256()
    total = 0
    try:
        before = os.fstat(descriptor)
        while chunk := os.read(descriptor, _READ_CHUNK_BYTES):
            total += len(chunk)
            if max_bytes is not None and total > max_bytes:
                raise BoundedFileError(path, f"size exceeds limit {max_bytes}")
            if total > identity.size:
                raise BoundedFileError(path, "file grew while hashing")
            digest.update(chunk)
        _require_unchanged(path, descriptor, before, named_before, total)
    except OSError as exc:
        if isinstance(exc, BoundedFileError):
            raise
        raise BoundedFileError(path, str(exc)) from exc
    finally:
        os.close(descriptor)
    return digest.hexdigest(), identity


def _require_unchanged(
    path: Path,
    descriptor: int,
    before: os.stat_result,
    named_before: os.stat_result,
    size: int,
) -> None:
    after = os.fstat(descriptor)
    named = os.lstat(path)
    # Keep each metadata channel continuous: on Windows fstat and lstat may
    # report different ctime meanings/precision for the same newly written file.
    # The named inode/size was tied to the descriptor by _open_regular_file.
    if (
        size != before.st_size
        or (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
            before.st_mode,
        )
        != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
            after.st_mode,
        )
        or not stat.S_ISREG(named.st_mode)
        or (
            named.st_dev,
            named.st_ino,
            named.st_size,
            named.st_mtime_ns,
            named.st_ctime_ns,
            named.st_mode,
        )
        != (
            named_before.st_dev,
            named_before.st_ino,
            named_before.st_size,
            named_before.st_mtime_ns,
            named_before.st_ctime_ns,
            named_before.st_mode,
        )
    ):
        raise BoundedFileError(path, "file identity or metadata changed while reading")


def _open_regular_file(
    path: Path,
    max_bytes: int | None,
    expected: FileIdentity | None,
) -> tuple[int, FileIdentity, os.stat_result]:
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
        | getattr(os, "O_NONBLOCK", 0)
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
    except OSError, BoundedFileError:
        os.close(descriptor)
        raise
    return descriptor, identity, before
