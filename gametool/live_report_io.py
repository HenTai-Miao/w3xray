"""Stable no-follow report reads and exclusive complete-file publication."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import stat
import sys
import tempfile
from typing import Any

from .durable_io import sync_directory, sync_file_descriptor
from .live_report_json import LiveReportError
from .report_file_proof import (
    cleanup_report_paths,
    report_metadata,
    require_report_payload,
)
from .windows_output_paths import (
    logical_output_path,
    native_output_path,
    validate_output_root,
)


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
        # Win32 abspath can erase trailing dots/spaces. Reject the caller's
        # original spelling before canonicalization changes its meaning.
        validate_output_root(text)
        return Path(os.path.abspath(logical_output_path(text)))
    except (TypeError, ValueError, OSError) as exc:
        raise LiveReportError(f"Invalid report path: {exc}") from exc


def _native(path: Path) -> Path:
    return Path(native_output_path(str(path)))


def _ancestors(path: Path) -> list[Path]:
    return [*reversed(path.parent.parents), path.parent]


def _check_directories(
    snapshots: list[tuple[Path, tuple[int, int, int]]],
) -> None:
    for directory, expected in snapshots:
        details = _native(directory).lstat()
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
    handle = create(
        native_output_path(str(path)),
        0,
        0x1 | 0x2,
        None,
        3,
        0x02000000 | 0x00200000,
        None,
    )
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
            details = _native(directory).lstat()
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
            if os.path.lexists(_native(target)):
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
    target_io = _native(target)
    try:
        with _parents(target) as parents:
            original = target_io.lstat()
            if _unsafe_link(original) or not stat.S_ISREG(original.st_mode):
                raise LiveReportError(
                    f"Report must be an ordinary regular file: {target}"
                )
            flags = (
                os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
            )
            descriptor = os.open(target_io, flags)
            with os.fdopen(descriptor, "rb") as stream:
                opened = os.fstat(stream.fileno())
                if _opened_identity(opened) != _opened_identity(original):
                    raise LiveReportError("Report identity changed during open")
                data = stream.read()
                if _identity(os.fstat(stream.fileno())) != _identity(opened):
                    raise LiveReportError("Report changed while being read")
            _check_directories(parents)
            if (
                _identity(target_io.lstat()) != _identity(original)
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
                "parents": [
                    {
                        "path": str(directory),
                        "device": identity[0],
                        "inode": identity[1],
                        "mode": identity[2],
                    }
                    for directory, identity in parents
                ],
            }
            return data, metadata
    except OSError as exc:
        raise LiveReportError(f"Cannot read report {target}: {exc}") from exc
    except MemoryError as exc:
        raise LiveReportError(
            "Report allocation failed; no partial report was delivered"
        ) from exc


def verify_report_source(metadata: dict[str, Any]) -> None:
    """Reprove every source byte and ancestor after analysis/serialization."""
    _data, actual = read_report_bytes(metadata["path"])
    if any(actual.get(key) != value for key, value in metadata.items()):
        raise LiveReportError("Report source changed before final delivery")


def write_report_bytes(
    path: str | os.PathLike[str],
    data: bytes,
    *,
    verify_source: Callable[[], None] | None = None,
) -> Path:
    """Publish a complete staged file without replacing any existing asset."""
    target = validate_report_destination(path)
    target_io = native_output_path(str(target))
    digest = hashlib.sha256(data).hexdigest()
    try:
        with _parents(target) as parents:
            descriptor, stage = tempfile.mkstemp(
                prefix=".gamexray-live-report-",
                suffix=".tmp",
                dir=native_output_path(str(target.parent)),
            )
            details = os.fstat(descriptor)
            stage_identity = details.st_dev, details.st_ino
            completed = created = False
            try:
                with os.fdopen(descriptor, "wb", closefd=False) as stream:
                    stream.write(data)
                    stream.flush()
                    sync_file_descriptor(stream.fileno())
                expected = report_metadata(os.fstat(descriptor))
                if expected[2] != len(data):
                    raise LiveReportError("Report stage length changed")
                _, named = require_report_payload(stage, descriptor, expected, digest)
                _check_directories(parents)
                if verify_source is not None:
                    verify_source()
                # Publish only the already verified inode; a concurrent owner
                # of the destination always wins without being overwritten.
                os.link(stage, target_io, follow_symlinks=False)
                created = True
                linked, _ = require_report_payload(
                    stage,
                    descriptor,
                    expected,
                    digest,
                    expected_named=named,
                    allow_link_change_time=True,
                )
                require_report_payload(
                    target_io, descriptor, linked, digest, expected_named=named
                )
                _check_directories(parents)
                sync_directory(_native(target.parent))
                if verify_source is not None:
                    verify_source()
                require_report_payload(
                    target_io, descriptor, linked, digest, expected_named=named
                )
                _check_directories(parents)
                completed = True
            finally:
                primary = sys.exc_info()[1]
                os.close(descriptor)
                retained = cleanup_report_paths(
                    (target_io, stage) if created and not completed else (stage,),
                    stage_identity,
                )
                if retained:
                    message = "; ".join(retained)
                    raise OSError(
                        f"{primary}; {message}" if primary is not None else message
                    ) from primary
        return target
    except OSError as exc:
        raise LiveReportError(f"Cannot publish fresh report {target}: {exc}") from exc
