"""Contained output paths and no-follow file writes."""

from __future__ import annotations

from collections.abc import Iterable
import errno
import os
from pathlib import PurePosixPath, PureWindowsPath
import tempfile
from typing import Final

from gametool.safe_output_anchored import (
    ANCHORED_WRITES_AVAILABLE as _ANCHORED_WRITES_AVAILABLE,
)
from gametool.safe_output_anchored import write_bytes_anchored
from gametool.safe_output_anchored import write_chunks_anchored
from gametool.safe_output_chunk_writer import write_chunks_to_descriptor
from gametool.safe_output_models import SafeWriteResult, SafeWriteStatus
from gametool.safe_output_path_publication import publish_staged_path
from gametool.windows_output_paths import (
    logical_output_path,
    native_output_path,
    validate_output_root,
    remove_owned_output,
)

_UNSAFE_OPEN_ERRNOS: Final = frozenset((errno.EISDIR, errno.ELOOP, errno.ENOTDIR))


def safe_relative_path(name: str) -> PurePosixPath | None:
    """Parse an untrusted name as a relative, traversal-free path."""
    try:
        _ = name.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return None
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
    try:
        validate_output_root(root)
        root_path = os.path.abspath(root)
        root_io = native_output_path(root_path)
        if os.path.islink(root_io):
            return None
        root_real = _real_output_path(root_path)
        destination = os.path.abspath(os.path.join(root_real, *relative.parts))
        destination_io = native_output_path(destination)
        current = root_real
        for part in relative.parts[:-1]:
            current = os.path.join(current, part)
            current_io = native_output_path(current)
            if os.path.lexists(current_io) and (
                os.path.islink(current_io) or not os.path.isdir(current_io)
            ):
                return None
            if not _within_root(root_real, _real_output_path(current)):
                return None
        if os.path.lexists(destination_io) and os.path.islink(destination_io):
            return None
        if not _within_root(root_real, _real_output_path(destination)):
            return None
    except OSError, ValueError:
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
            prefix=".gamexray-stage-",
            suffix=".tmp",
            dir=native_output_path(parent),
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
            publish_staged_path(
                staged_path, destination, expected_stage_identity=staged_identity
            )
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
        details = os.stat(native_output_path(path), follow_symlinks=False)
    except FileNotFoundError:
        return "staged output disappeared before publication"
    if (details.st_dev, details.st_ino) != identity:
        return "staged output changed before publication"
    return None


def _remove_owned_staged_path(path: str, identity: tuple[int, int]) -> None:
    _ = remove_owned_output(path, identity)


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
    destination = root
    try:
        validate_output_root(root)
        root_path = os.path.abspath(root)
        destination = os.path.join(root_path, *relative.parts)
        root_io = native_output_path(root_path)
        # Validate every untrusted component before creating any directory.
        _ = native_output_path(destination)
        if os.path.islink(root_io):
            return root_path, SafeWriteStatus.UNSAFE, "output root is a symlink"
        os.makedirs(root_io, exist_ok=True)
        if os.path.islink(root_io):
            return root_path, SafeWriteStatus.UNSAFE, "output root is a symlink"
        root_real = _real_output_path(root_path)
        current = root_real
        for part in relative.parts[:-1]:
            current = os.path.join(current, part)
            current_io = native_output_path(current)
            if not os.path.lexists(current_io):
                try:
                    os.mkdir(current_io, 0o700)
                except FileExistsError:
                    if not os.path.isdir(current_io):
                        return (
                            current,
                            SafeWriteStatus.UNSAFE,
                            "parent is not a directory",
                        )
            if os.path.islink(current_io) or not os.path.isdir(current_io):
                return current, SafeWriteStatus.UNSAFE, "unsafe parent component"
            if not _within_root(root_real, _real_output_path(current)):
                return current, SafeWriteStatus.UNSAFE, "parent escapes output root"
        destination = os.path.join(current, relative.name)
        destination_io = native_output_path(destination)
        if os.path.lexists(destination_io) and (
            os.path.islink(destination_io) or os.path.isdir(destination_io)
        ):
            return destination, SafeWriteStatus.UNSAFE, "unsafe destination"
        if not _within_root(root_real, _real_output_path(destination)):
            return (
                destination,
                SafeWriteStatus.UNSAFE,
                "destination escapes output root",
            )
    except ValueError as exc:
        return destination, SafeWriteStatus.UNSAFE, str(exc)
    except OSError as exc:
        return destination, _open_failure_status(exc), str(exc)
    return destination, None, ""


def _real_output_path(path: str) -> str:
    """Resolve through the long-path I/O spelling, then compare logical paths."""
    resolved = os.path.realpath(native_output_path(path))
    if os.name == "nt" and path.startswith("\\\\?\\"):
        return resolved
    return logical_output_path(resolved)


def _within_root(root: str, path: str) -> bool:
    try:
        return os.path.commonpath((root, path)) == root
    except ValueError:
        return False
