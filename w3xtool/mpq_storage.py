"""Owned byte storage for MPQ archives."""

from __future__ import annotations

import mmap
import os
import shutil
import stat
import tempfile
from dataclasses import dataclass
from mmap import mmap as MMap
from typing import BinaryIO, Final, override

type ArchiveBytes = bytes | MMap

_MMAP_THRESHOLD: Final = 40 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class MPQStorageError(OSError):
    """A source path cannot provide one stable regular-file snapshot."""

    path: str
    reason: str

    @override
    def __str__(self) -> str:
        return f"cannot read regular MPQ file {self.path}: {self.reason}"


@dataclass(slots=True)  # noqa: MUTABLE_OK - this object owns closeable state.
class MPQBackingStore:
    """Own mutable archive bytes, an optional source handle, and a temp copy."""

    data: ArchiveBytes
    handle: BinaryIO | None
    temporary_path: str | None

    def close(self) -> None:
        """Release every owned resource; repeated calls are harmless."""
        if isinstance(self.data, MMap):
            try:
                self.data.close()
            except (BufferError, OSError):
                return
            except ValueError:
                self.data = b""
            else:
                self.data = b""
        if self.handle is not None:
            try:
                self.handle.close()
            except OSError:
                return
            self.handle = None
        if self.temporary_path is not None:
            try:
                os.remove(self.temporary_path)
            except FileNotFoundError:
                self.temporary_path = None
            except OSError:
                return
            else:
                self.temporary_path = None


def open_mpq_backing(path: str) -> MPQBackingStore:
    """Open the source, falling back to an owned copy for OS open failures."""
    try:
        return _open_path(path, temporary_path=None)
    except MPQStorageError:
        raise
    except (OSError, ValueError):
        descriptor, temporary_path = tempfile.mkstemp(
            suffix=os.path.splitext(path)[1] or ".w3x",
        )
        os.close(descriptor)
        try:
            shutil.copyfile(path, temporary_path)
            store = _open_path(temporary_path, temporary_path=temporary_path)
        except (OSError, ValueError) as error:
            try:
                os.remove(temporary_path)
            except OSError as cleanup_error:
                error.add_note(
                    f"temporary cleanup failed for {temporary_path}: {cleanup_error}"
                )
            raise
        if store.handle is None:
            try:
                os.remove(temporary_path)
            except FileNotFoundError:
                store.temporary_path = None
            except OSError:
                return store
            else:
                store.temporary_path = None
    return store


def open_regular_binary(path: str) -> tuple[BinaryIO, int]:
    """Open one regular-file descriptor without blocking on special files."""
    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    descriptor = os.open(path, flags)
    transfer_descriptor = False
    try:
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode):
            raise MPQStorageError(path, "path is not a regular file")
        handle = os.fdopen(descriptor, "rb")
        transfer_descriptor = True
        return handle, details.st_size
    finally:
        if not transfer_descriptor:
            os.close(descriptor)


def _open_path(path: str, *, temporary_path: str | None) -> MPQBackingStore:
    handle, size = open_regular_binary(path)
    transfer_handle = False
    try:
        if size <= _MMAP_THRESHOLD:
            data = handle.read(size + 1)
            if len(data) != size:
                raise MPQStorageError(path, "file size changed while reading")
            return MPQBackingStore(
                data=data,
                handle=None,
                temporary_path=temporary_path,
            )
        data = mmap.mmap(handle.fileno(), size, access=mmap.ACCESS_READ)
        transfer_handle = True
        return MPQBackingStore(
            data=data,
            handle=handle,
            temporary_path=temporary_path,
        )
    finally:
        if not transfer_handle:
            handle.close()
