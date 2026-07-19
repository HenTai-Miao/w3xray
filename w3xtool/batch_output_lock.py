"""Cross-process ownership lease for one batch output root."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import errno
import os
from pathlib import Path
import stat
from typing import Final

from .batch_configuration import BatchOutputError
from .durable_io import sync_directory, sync_file_descriptor


_LOCK_NAME: Final = ".w3xray-output.lock"
_DIRECTORY_DESCRIPTORS_AVAILABLE: Final = os.name != "nt"
_CONTENTION_ERRNOS: Final = frozenset(
    (errno.EACCES, errno.EAGAIN, errno.EDEADLK, errno.EWOULDBLOCK)
)


@dataclass(frozen=True, slots=True)
class BatchOutputLease:
    """Open descriptors proving exclusive ownership of one stable output root."""

    root: Path
    root_descriptor: int
    lock_descriptor: int
    root_device: int
    root_inode: int
    lock_device: int
    lock_inode: int


@contextmanager
def hold_batch_output_lock(output_root: str | Path) -> Iterator[BatchOutputLease]:
    """Acquire one non-blocking process lease and retain it through publication."""
    root = Path(os.path.abspath(os.fspath(output_root)))
    if root.is_symlink():
        raise BatchOutputError(str(root), "output root is a symlink")
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise BatchOutputError(str(root), "output root is unsafe")
    root_descriptor, root_status = _open_root_binding(root)
    lock_descriptor = -1
    locked = False
    try:
        lock_descriptor = _open_lock_file(root)
        try:
            _lock_descriptor(lock_descriptor)
        except OSError as exc:
            if exc.errno in _CONTENTION_ERRNOS:
                raise BatchOutputError(
                    str(root / _LOCK_NAME),
                    "output root is in use",
                ) from exc
            raise
        locked = True
        lock_status = os.fstat(lock_descriptor)
        lease = BatchOutputLease(
            root,
            root_descriptor,
            lock_descriptor,
            root_status.st_dev,
            root_status.st_ino,
            lock_status.st_dev,
            lock_status.st_ino,
        )
        if not lease_is_current(lease, root):
            raise BatchOutputError(str(root), "output root changed during lock")
        yield lease
    finally:
        try:
            if locked:
                _unlock_descriptor(lock_descriptor)
        finally:
            try:
                if lock_descriptor >= 0:
                    os.close(lock_descriptor)
            finally:
                if root_descriptor >= 0:
                    os.close(root_descriptor)


def lease_is_current(lease: BatchOutputLease, output_root: str | Path) -> bool:
    """Confirm that open lease descriptors still name the requested paths."""
    root = Path(os.path.abspath(os.fspath(output_root)))
    if root != lease.root:
        return False
    try:
        root_path = os.lstat(root)
        lock_path = os.lstat(root / _LOCK_NAME)
        lock_open = os.fstat(lease.lock_descriptor)
    except OSError:
        return False
    root_descriptor_is_current = True
    if lease.root_descriptor >= 0:
        try:
            root_open = os.fstat(lease.root_descriptor)
        except OSError:
            return False
        root_descriptor_is_current = bool(
            stat.S_ISDIR(root_open.st_mode)
            and (root_open.st_dev, root_open.st_ino)
            == (lease.root_device, lease.root_inode)
        )
    return bool(
        stat.S_ISDIR(root_path.st_mode)
        and not stat.S_ISLNK(root_path.st_mode)
        and (root_path.st_dev, root_path.st_ino)
        == (lease.root_device, lease.root_inode)
        and root_descriptor_is_current
        and stat.S_ISREG(lock_path.st_mode)
        and stat.S_ISREG(lock_open.st_mode)
        and (lock_path.st_dev, lock_path.st_ino)
        == (lease.lock_device, lease.lock_inode)
        == (lock_open.st_dev, lock_open.st_ino)
    )


def _open_root_binding(path: Path) -> tuple[int, os.stat_result]:
    if not _DIRECTORY_DESCRIPTORS_AVAILABLE:
        opened = os.lstat(path)
        if stat.S_ISLNK(opened.st_mode) or not stat.S_ISDIR(opened.st_mode):
            raise BatchOutputError(str(path), "output root is not a directory")
        return -1, opened
    descriptor = _open_directory(path)
    return descriptor, os.fstat(descriptor)


def _open_directory(path: Path) -> int:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(path, flags)
    opened = os.fstat(descriptor)
    if not stat.S_ISDIR(opened.st_mode):
        os.close(descriptor)
        raise BatchOutputError(str(path), "output root is not a directory")
    return descriptor


def _open_lock_file(root: Path) -> int:
    path = root / _LOCK_NAME
    common = (
        os.O_RDWR
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(path, common | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        descriptor = os.open(path, common)
    else:
        _ = os.write(descriptor, b"\0")
        sync_file_descriptor(descriptor)
        sync_directory(root)
    opened = os.fstat(descriptor)
    if not stat.S_ISREG(opened.st_mode) or opened.st_size < 1:
        os.close(descriptor)
        raise BatchOutputError(str(path), "output lock file is unsafe")
    return descriptor


def _lock_descriptor(descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt

        _ = os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        return
    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_descriptor(descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt

        _ = os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_UN)


__all__ = ("BatchOutputLease", "hold_batch_output_lock", "lease_is_current")
