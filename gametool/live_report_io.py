"""Stable no-follow report reads and exclusive complete-file publication."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import stat
import tempfile
from typing import Any

from .durable_io import sync_directory, sync_file_descriptor
from .live_report_json import LiveReportError


def _identity(details: os.stat_result) -> tuple[int, ...]:
    return (
        details.st_dev,
        details.st_ino,
        details.st_size,
        details.st_mtime_ns,
        details.st_ctime_ns,
        details.st_mode,
    )


def _directory_identity(details: os.stat_result) -> tuple[int, int, int]:
    # Directory timestamps change when our own stage is created/linked.
    return details.st_dev, details.st_ino, details.st_mode


def _opened_identity(details: os.stat_result) -> tuple[int, ...]:
    # On Windows pathname stat and descriptor stat expose different ctime
    # semantics (creation versus change time). Compare each clock only against
    # the same API, while binding the open using inode/device/size/mtime/mode.
    return (
        details.st_dev,
        details.st_ino,
        details.st_size,
        details.st_mtime_ns,
        details.st_mode,
    )


def _unsafe_link(details: os.stat_result) -> bool:
    return stat.S_ISLNK(details.st_mode) or bool(
        getattr(details, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _absolute(path: str | os.PathLike[str]) -> Path:
    try:
        text = os.fspath(path)
        if not isinstance(text, str):
            raise LiveReportError("Report paths must be Unicode text")
        text.encode("utf-8", errors="strict")
        if not text or "\0" in text:
            raise LiveReportError("Report path must be a nonempty ordinary path")
        return Path(os.path.abspath(text))
    except (TypeError, UnicodeError, OSError) as exc:
        raise LiveReportError(f"Invalid report path: {exc}") from exc


def _ancestors(path: Path) -> list[Path]:
    return [*reversed(path.parent.parents), path.parent]


def _check_directories(
    snapshots: list[tuple[Path, tuple[int, int, int]]],
) -> None:
    for directory, expected in snapshots:
        details = directory.lstat()
        if _unsafe_link(details) or _directory_identity(details) != expected:
            raise LiveReportError(
                f"Report parent changed or became a link: {directory}"
            )


@contextmanager
def _windows_directory_handle(path: Path) -> Iterator[None]:
    """Prevent Windows parent renames while a report operation is in flight."""
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    # Share reads/writes, but not deletion/rename. Open reparse points themselves.
    handle = create(str(path), 0, 0x1 | 0x2, None, 3, 0x02000000 | 0x00200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield
    finally:
        close(handle)


@contextmanager
def _parents(path: Path) -> Iterator[list[tuple[Path, tuple[int, int, int]]]]:
    from contextlib import ExitStack

    snapshots: list[tuple[Path, tuple[int, int, int]]] = []
    with ExitStack() as held:
        for directory in _ancestors(path):
            details = directory.lstat()
            if _unsafe_link(details) or not stat.S_ISDIR(details.st_mode):
                raise LiveReportError(
                    f"Report parent must be an ordinary directory: {directory}"
                )
            snapshots.append((directory, _directory_identity(details)))
            if os.name == "nt":
                held.enter_context(_windows_directory_handle(directory))
            elif hasattr(os, "O_NOFOLLOW"):
                descriptor = os.open(
                    directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                )
                held.callback(os.close, descriptor)
                if _directory_identity(os.fstat(descriptor)) != _directory_identity(
                    details
                ):
                    raise LiveReportError(
                        f"Report parent changed during open: {directory}"
                    )
        _check_directories(snapshots)
        yield snapshots
        _check_directories(snapshots)


def validate_report_destination(path: str | os.PathLike[str]) -> Path:
    """Preflight a fresh report name; publication performs the authoritative check."""
    target = _absolute(path)
    try:
        with _parents(target):
            if os.path.lexists(target):
                raise LiveReportError(
                    f"Report destination already exists; choose a new filename: {target}"
                )
            if target.name in {"", ".", ".."}:
                raise LiveReportError("A report filename is required")
    except OSError as exc:
        raise LiveReportError(f"Cannot use report destination {target}: {exc}") from exc
    return target


def read_report_bytes(path: str | os.PathLike[str]) -> tuple[bytes, dict[str, Any]]:
    """Read the complete regular file and prove source/ancestor stability."""
    target = _absolute(path)
    try:
        with _parents(target) as parents:
            original = target.lstat()
            if _unsafe_link(original) or not stat.S_ISREG(original.st_mode):
                raise LiveReportError(
                    f"Report must be an ordinary regular file: {target}"
                )
            flags = (
                os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
            )
            descriptor = os.open(target, flags)
            with os.fdopen(descriptor, "rb") as stream:
                opened = os.fstat(stream.fileno())
                if _opened_identity(opened) != _opened_identity(original):
                    raise LiveReportError("Report identity changed during open")
                data = stream.read()
                if _identity(os.fstat(stream.fileno())) != _identity(opened):
                    raise LiveReportError("Report changed while being read")
            _check_directories(parents)
            if (
                _identity(target.lstat()) != _identity(original)
                or len(data) != original.st_size
            ):
                raise LiveReportError("Report source changed before delivery")
            metadata = {
                "path": str(target),
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data),
                "device": original.st_dev,
                "inode": original.st_ino,
                "mtime_ns": original.st_mtime_ns,
                "ctime_ns": original.st_ctime_ns,
                "opened_ctime_ns": opened.st_ctime_ns,
            }
            return data, metadata
    except OSError as exc:
        raise LiveReportError(f"Cannot read report {target}: {exc}") from exc
    except MemoryError as exc:
        raise LiveReportError(
            "Report allocation failed; no partial report was delivered"
        ) from exc


def verify_report_source(metadata: dict[str, Any]) -> None:
    """Recheck source identity after complete JSON validation."""
    path = Path(metadata["path"])
    try:
        with _parents(path):
            details = path.lstat()
            expected = (
                metadata["device"],
                metadata["inode"],
                metadata["size"],
                metadata["mtime_ns"],
                metadata["ctime_ns"],
            )
            actual = (
                details.st_dev,
                details.st_ino,
                details.st_size,
                details.st_mtime_ns,
                details.st_ctime_ns,
            )
            if (
                _unsafe_link(details)
                or not stat.S_ISREG(details.st_mode)
                or actual != expected
            ):
                raise LiveReportError("Report source changed during JSON validation")
            descriptor = os.open(
                path,
                os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0),
            )
            try:
                opened = os.fstat(descriptor)
                if (
                    _opened_identity(opened) != _opened_identity(details)
                    or opened.st_ctime_ns != metadata["opened_ctime_ns"]
                ):
                    raise LiveReportError(
                        "Report source changed during JSON validation"
                    )
            finally:
                os.close(descriptor)
    except OSError as exc:
        raise LiveReportError(
            f"Report source unavailable after validation: {exc}"
        ) from exc


def write_report_bytes(path: str | os.PathLike[str], data: bytes) -> Path:
    """Publish a complete staged file without replacing any existing asset."""
    target = validate_report_destination(path)
    stage: Path | None = None
    stage_identity: tuple[int, int] | None = None
    try:
        with _parents(target) as parents:
            descriptor, name = tempfile.mkstemp(
                prefix=".gamexray-live-report-", suffix=".tmp", dir=target.parent
            )
            stage = Path(name)
            details = os.fstat(descriptor)
            stage_identity = details.st_dev, details.st_ino
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                sync_file_descriptor(stream.fileno())
            _check_directories(parents)
            staged = stage.lstat()
            if _unsafe_link(staged) or (staged.st_dev, staged.st_ino) != stage_identity:
                raise LiveReportError(
                    "Report stage identity changed before publication"
                )
            # A hard link publishes the already complete inode atomically and
            # fails if a concurrent writer claimed the destination name.
            os.link(stage, target, follow_symlinks=False)
            _check_directories(parents)
            published = target.lstat()
            if (
                _unsafe_link(published)
                or (published.st_dev, published.st_ino) != stage_identity
            ):
                raise LiveReportError(
                    "Published report identity changed; concurrent file retained"
                )
            sync_directory(target.parent)
        return target
    except OSError as exc:
        raise LiveReportError(f"Cannot publish fresh report {target}: {exc}") from exc
    finally:
        if stage is not None and stage_identity is not None:
            try:
                details = stage.lstat()
                if (
                    not _unsafe_link(details)
                    and (details.st_dev, details.st_ino) == stage_identity
                ):
                    stage.unlink()
            except OSError:
                # Preserve a stage whose ownership or cleanup is uncertain.
                pass
