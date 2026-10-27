"""Owned byte storage for MPQ archives."""

from __future__ import annotations

import mmap
import os
import shutil
import stat
import tempfile
from dataclasses import dataclass
from mmap import mmap as MMap
from typing import BinaryIO, Final, Protocol, override, runtime_checkable

type ArchiveBytes = bytes | MMap

_MMAP_THRESHOLD: Final = 40 * 1024 * 1024


class MPQStorageError(OSError):
    """A source path cannot provide one stable regular-file snapshot."""

    def __init__(self, path: str, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(path, reason)

    @override
    def __str__(self) -> str:
        return f"cannot read regular MPQ file {self.path}: {self.reason}"


@dataclass(frozen=True, slots=True)
class MPQSourceIdentity:
    """Exact regular-file identity and metadata bound to an archive snapshot."""

    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int
    mode: int


@runtime_checkable
class SourceIdentityArchive(Protocol):
    @property
    def source_identity(self) -> MPQSourceIdentity | None: ...

    def verify_source(self) -> None: ...


@dataclass(slots=True)  # [OK: MUTABLE_OK] - this object owns closeable state.
class MPQBackingStore:
    """Own mutable archive bytes, an optional source handle, and a temp copy."""

    data: ArchiveBytes
    handle: BinaryIO | None
    temporary_path: str | None
    source_path: str | None = None
    source_identity: MPQSourceIdentity | None = None

    def verify_source(self) -> None:
        """Reject mutation or replacement of the source captured by this store."""
        if self.source_path is None or self.source_identity is None:
            return
        source_handle = self.handle if self.temporary_path is None else None
        _require_source_identity(self.source_path, self.source_identity, source_handle)

    def close(self) -> None:
        """Release every owned resource; repeated calls are harmless."""
        if isinstance(self.data, MMap):
            try:
                self.data.close()
            except BufferError, OSError:
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
    except OSError, ValueError:
        source_handle, _source_size = open_regular_binary(path)
        try:
            source_identity = _source_identity(os.fstat(source_handle.fileno()))
        finally:
            source_handle.close()
        descriptor, temporary_path = tempfile.mkstemp(
            suffix=os.path.splitext(path)[1] or ".w3x",
        )
        os.close(descriptor)
        store: MPQBackingStore | None = None
        try:
            shutil.copyfile(path, temporary_path)
            store = _open_path(temporary_path, temporary_path=temporary_path)
            _require_source_identity(path, source_identity)
            store.source_path = path
            store.source_identity = source_identity
        except (OSError, ValueError) as error:
            if store is not None:
                store.close()
            try:
                os.remove(temporary_path)
            except FileNotFoundError:
                pass
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
        identity = _source_identity(os.fstat(handle.fileno()))
        if identity.size != size:
            raise MPQStorageError(path, "source size changed before reading")
        if size <= _MMAP_THRESHOLD:
            data = handle.read(size + 1)
            if len(data) != size:
                raise MPQStorageError(path, "file size changed while reading")
            _require_source_identity(path, identity, handle)
            return MPQBackingStore(
                data=data,
                handle=None,
                temporary_path=temporary_path,
                source_path=path,
                source_identity=identity,
            )
        data = mmap.mmap(handle.fileno(), size, access=mmap.ACCESS_READ)
        try:
            _require_source_identity(path, identity, handle)
        except OSError:
            data.close()
            raise
        transfer_handle = True
        return MPQBackingStore(
            data=data,
            handle=handle,
            temporary_path=temporary_path,
            source_path=path,
            source_identity=identity,
        )
    finally:
        if not transfer_handle:
            handle.close()


def _source_identity(details: os.stat_result) -> MPQSourceIdentity:
    return MPQSourceIdentity(
        details.st_dev,
        details.st_ino,
        details.st_size,
        details.st_mtime_ns,
        details.st_ctime_ns,
        details.st_mode,
    )


def _require_source_identity(
    path: str, expected: MPQSourceIdentity, handle: BinaryIO | None = None
) -> None:
    verification_handle: BinaryIO | None = None
    try:
        if handle is None:
            verification_handle, _size = open_regular_binary(path)
            handle = verification_handle
        named = os.stat(path)
        opened = os.fstat(handle.fileno())
    except OSError as exc:
        raise MPQStorageError(
            path, f"source identity cannot be verified: {exc}"
        ) from exc
    finally:
        if verification_handle is not None:
            verification_handle.close()
    # Windows path stat exposes creation time as ctime, while descriptor fstat
    # exposes the file change time. Compare change times only through fstat.
    if (
        not stat.S_ISREG(named.st_mode)
        or (named.st_dev, named.st_ino, named.st_size, named.st_mtime_ns, named.st_mode)
        != (
            expected.device,
            expected.inode,
            expected.size,
            expected.mtime_ns,
            expected.mode,
        )
        or _source_identity(opened) != expected
    ):
        raise MPQStorageError(path, "source identity or metadata changed while reading")
