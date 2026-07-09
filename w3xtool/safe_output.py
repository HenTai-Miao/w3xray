"""Contained output paths and no-follow file writes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import errno
import os
from pathlib import PurePosixPath, PureWindowsPath


class SafeWriteStatus(StrEnum):
    WRITTEN = "written"
    UNSAFE = "unsafe"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class SafeWriteResult:
    status: SafeWriteStatus
    path: str
    size: int
    error: str = ""


def safe_relative_path(name: str) -> PurePosixPath | None:
    """Parse an untrusted name as a relative, traversal-free path."""
    if not name or "\0" in name or name.startswith(("/", "\\")):
        return None
    if PureWindowsPath(name).drive:
        return None
    parts = tuple(
        part
        for part in name.replace("\\", "/").split("/")
        if part not in ("", ".")
    )
    if not parts or ".." in parts:
        return None
    return PurePosixPath(*parts)


def safe_destination(root: str, name: str) -> str | None:
    """Return the logical destination when it remains inside the root."""
    relative = safe_relative_path(name)
    if relative is None:
        return None
    root_path = os.path.abspath(root)
    if os.path.islink(root_path):
        return None
    root_real = os.path.realpath(root_path)
    destination = os.path.abspath(os.path.join(root_real, *relative.parts))
    current = root_real
    for part in relative.parts[:-1]:
        current = os.path.join(current, part)
        if os.path.lexists(current) and (
            os.path.islink(current) or not os.path.isdir(current)
        ):
            return None
        if not _within_root(root_real, os.path.realpath(current)):
            return None
    if os.path.lexists(destination) and os.path.islink(destination):
        return None
    if not _within_root(root_real, os.path.realpath(destination)):
        return None
    return destination


def write_bytes_safely(root: str, name: str, data: bytes) -> SafeWriteResult:
    """Write bytes below root without following destination symlinks."""
    destination, status, error = _prepare_destination(root, name)
    if status is not None:
        return SafeWriteResult(status, destination, 0, error)
    flags = os.O_CREAT | os.O_TRUNC | os.O_WRONLY
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(destination, flags, 0o600)
    except OSError as exc:
        failure = SafeWriteStatus.UNSAFE if exc.errno == errno.ELOOP else SafeWriteStatus.FAILED
        return SafeWriteResult(failure, destination, 0, str(exc))
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
    except OSError as exc:
        return SafeWriteResult(SafeWriteStatus.FAILED, destination, 0, str(exc))
    return SafeWriteResult(SafeWriteStatus.WRITTEN, destination, len(data))


def write_text_safely(
    root: str,
    name: str,
    text: str,
    *,
    encoding: str = "utf-8",
) -> SafeWriteResult:
    """Encode and safely write text below root."""
    return write_bytes_safely(root, name, text.encode(encoding))


def _prepare_destination(
    root: str,
    name: str,
) -> tuple[str, SafeWriteStatus | None, str]:
    relative = safe_relative_path(name)
    if relative is None:
        return "", SafeWriteStatus.UNSAFE, "unsafe relative path"
    root_path = os.path.abspath(root)
    if os.path.islink(root_path):
        return root_path, SafeWriteStatus.UNSAFE, "output root is a symlink"
    try:
        os.makedirs(root_path, exist_ok=True)
    except OSError as exc:
        return root_path, SafeWriteStatus.FAILED, str(exc)
    if os.path.islink(root_path):
        return root_path, SafeWriteStatus.UNSAFE, "output root is a symlink"
    root_real = os.path.realpath(root_path)
    current = root_real
    for part in relative.parts[:-1]:
        current = os.path.join(current, part)
        if not os.path.lexists(current):
            try:
                os.mkdir(current, 0o700)
            except FileExistsError:
                if not os.path.isdir(current):
                    return current, SafeWriteStatus.UNSAFE, "parent is not a directory"
            except OSError as exc:
                return current, SafeWriteStatus.FAILED, str(exc)
        if os.path.islink(current) or not os.path.isdir(current):
            return current, SafeWriteStatus.UNSAFE, "unsafe parent component"
        if not _within_root(root_real, os.path.realpath(current)):
            return current, SafeWriteStatus.UNSAFE, "parent escapes output root"
    destination = os.path.join(current, relative.name)
    if os.path.lexists(destination) and (
        os.path.islink(destination) or os.path.isdir(destination)
    ):
        return destination, SafeWriteStatus.UNSAFE, "unsafe destination"
    if not _within_root(root_real, os.path.realpath(destination)):
        return destination, SafeWriteStatus.UNSAFE, "destination escapes output root"
    return destination, None, ""


def _within_root(root: str, path: str) -> bool:
    try:
        return os.path.commonpath((root, path)) == root
    except ValueError:
        return False
