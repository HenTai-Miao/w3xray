"""Contained output paths and no-follow file writes."""

from __future__ import annotations

from collections.abc import Iterable
import errno
import os
from pathlib import PurePosixPath, PureWindowsPath
import tempfile
from typing import Final

from w3xtool.safe_output_anchored import (
    ANCHORED_WRITES_AVAILABLE as _ANCHORED_WRITES_AVAILABLE,
)
from w3xtool.safe_output_anchored import write_bytes_anchored
from w3xtool.safe_output_anchored import write_chunks_anchored
from w3xtool.safe_output_chunk_writer import write_chunks_to_descriptor
from w3xtool.safe_output_models import SafeWriteResult, SafeWriteStatus
from w3xtool.safe_output_path_publication import publish_staged_path

_UNSAFE_OPEN_ERRNOS: Final = frozenset((errno.EISDIR, errno.ELOOP, errno.ENOTDIR))


def safe_relative_path(name: str) -> PurePosixPath | None:
    """Parse an untrusted name as a relative, traversal-free path."""
    if not name or "\0" in name or name.startswith(("/", "\\")):
        return None
    if PureWindowsPath(name).drive:
        return None
    parts = tuple(
        part for part in name.replace("\\", "/").split("/") if part not in ("", ".")
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
    relative = safe_relative_path(name)
    if relative is None:
        return SafeWriteResult(SafeWriteStatus.UNSAFE, "", 0, "unsafe relative path")
    if _ANCHORED_WRITES_AVAILABLE:
        return write_bytes_anchored(root, relative, data)
    return _write_bytes_by_path(root, name, data)


def write_chunks_safely(
    root: str,
    name: str,
    chunks: Iterable[bytes],
) -> SafeWriteResult:
    """Write bounded chunks to a stage and publish only the complete output."""
    relative = safe_relative_path(name)
    if relative is None:
        return SafeWriteResult(SafeWriteStatus.UNSAFE, "", 0, "unsafe relative path")
    if _ANCHORED_WRITES_AVAILABLE:
        return write_chunks_anchored(root, relative, chunks)
    return _write_chunks_by_path(root, name, chunks)


def _write_bytes_by_path(root: str, name: str, data: bytes) -> SafeWriteResult:
    """Stage bytes on platforms without anchored directory operations."""
    return _write_chunks_by_path(root, name, (data,))


def _write_chunks_by_path(
    root: str,
    name: str,
    chunks: Iterable[bytes],
) -> SafeWriteResult:
    """Stage chunks beside the destination on platforms without dir-fd APIs."""
    destination, status, error = _prepare_destination(root, name)
    if status is not None:
        return SafeWriteResult(status, destination, 0, error)
    parent = os.path.dirname(destination)
    try:
        descriptor, staged_path = tempfile.mkstemp(
            prefix=".w3xray-stage-",
            suffix=".tmp",
            dir=parent,
        )
    except OSError as exc:
        return SafeWriteResult(_open_failure_status(exc), destination, 0, str(exc))
    staged_identity = _descriptor_identity(descriptor)
    try:
        try:
            size = write_chunks_to_descriptor(descriptor, chunks)
        except OSError as exc:
            return SafeWriteResult(SafeWriteStatus.FAILED, destination, 0, str(exc))
        finally:
            os.close(descriptor)
        stage_error = _staged_path_error(staged_path, staged_identity)
        if stage_error is not None:
            return SafeWriteResult(SafeWriteStatus.UNSAFE, destination, 0, stage_error)
        checked_destination, status, error = _prepare_destination(root, name)
        if status is not None:
            return SafeWriteResult(status, checked_destination, 0, error)
        if checked_destination != destination:
            return SafeWriteResult(
                SafeWriteStatus.UNSAFE,
                checked_destination,
                0,
                "output destination changed before publication",
            )
        stage_error = _staged_path_error(staged_path, staged_identity)
        if stage_error is not None:
            return SafeWriteResult(SafeWriteStatus.UNSAFE, destination, 0, stage_error)
        try:
            publish_staged_path(staged_path, destination)
        except OSError as exc:
            return SafeWriteResult(_open_failure_status(exc), destination, 0, str(exc))
        return SafeWriteResult(SafeWriteStatus.WRITTEN, destination, size)
    finally:
        _remove_owned_staged_path(staged_path, staged_identity)


def _descriptor_identity(descriptor: int) -> tuple[int, int]:
    details = os.fstat(descriptor)
    return details.st_dev, details.st_ino


def _staged_path_error(path: str, identity: tuple[int, int]) -> str | None:
    try:
        details = os.stat(path, follow_symlinks=False)
    except FileNotFoundError:
        return "staged output disappeared before publication"
    if (details.st_dev, details.st_ino) != identity:
        return "staged output changed before publication"
    return None


def _remove_owned_staged_path(path: str, identity: tuple[int, int]) -> None:
    try:
        details = os.stat(path, follow_symlinks=False)
    except FileNotFoundError:
        return
    if (details.st_dev, details.st_ino) == identity:
        os.unlink(path)


def _open_failure_status(exc: OSError) -> SafeWriteStatus:
    if exc.errno in _UNSAFE_OPEN_ERRNOS:
        return SafeWriteStatus.UNSAFE
    return SafeWriteStatus.FAILED


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
