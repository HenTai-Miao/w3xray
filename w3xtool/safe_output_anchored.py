"""Portable best-effort directory-fd containment for output writes.

Repeated ancestry checks detect completed directory moves around a write.
They do not provide Linux ``openat2``-style atomic path resolution against a
directory that is continuously renamed between checks.
"""

from __future__ import annotations

from contextlib import ExitStack
import errno
import os
from pathlib import PurePosixPath
from typing import Final

from w3xtool.safe_output_models import SafeWriteResult, SafeWriteStatus
from w3xtool.safe_output_publication import publish_staged_file
from w3xtool.safe_output_staging import (
    destination_error,
    discard_file,
    open_staged_file,
    remove_owned_staged_file,
)


ANCHORED_WRITES_AVAILABLE: Final = (
    os.open in os.supports_dir_fd
    and os.link in os.supports_dir_fd
    and os.mkdir in os.supports_dir_fd
    and os.rename in os.supports_dir_fd
    and os.stat in os.supports_dir_fd
    and os.unlink in os.supports_dir_fd
    and os.link in os.supports_follow_symlinks
    and os.stat in os.supports_follow_symlinks
    and hasattr(os, "O_DIRECTORY")
    and hasattr(os, "O_NOFOLLOW")
)
_DIRECTORY_OPEN_FLAGS: Final = (
    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
)
_UNSAFE_OPEN_ERRNOS: Final = frozenset((errno.EISDIR, errno.ELOOP, errno.ENOTDIR))


def write_bytes_anchored(
    root: str,
    relative: PurePosixPath,
    data: bytes,
) -> SafeWriteResult:
    """Write below a held root fd and reject completed parent moves."""
    root_path = os.path.abspath(root)
    if os.path.islink(root_path):
        return SafeWriteResult(
            SafeWriteStatus.UNSAFE,
            root_path,
            0,
            "output root is a symlink",
        )
    try:
        os.makedirs(root_path, exist_ok=True)
    except OSError as exc:
        return SafeWriteResult(SafeWriteStatus.FAILED, root_path, 0, str(exc))
    root_real = os.path.realpath(root_path)
    destination = os.path.join(root_real, *relative.parts)
    try:
        root_descriptor = os.open(root_path, _DIRECTORY_OPEN_FLAGS)
    except OSError as exc:
        return SafeWriteResult(_open_failure_status(exc), root_path, 0, str(exc))

    with ExitStack() as directories:
        _ = directories.callback(os.close, root_descriptor)
        parent_descriptor = root_descriptor
        current_path = root_real
        for part in relative.parts[:-1]:
            current_path = os.path.join(current_path, part)
            try:
                parent_descriptor = _open_or_create_directory(
                    parent_descriptor,
                    part,
                )
            except OSError as exc:
                return SafeWriteResult(
                    _open_failure_status(exc),
                    current_path,
                    0,
                    str(exc),
                )
            _ = directories.callback(os.close, parent_descriptor)
        return _write_from_parent(
            root_descriptor,
            parent_descriptor,
            relative.name,
            destination,
            data,
        )


def _write_from_parent(
    root_descriptor: int,
    parent_descriptor: int,
    name: str,
    destination: str,
    data: bytes,
) -> SafeWriteResult:
    containment_error = _containment_error(root_descriptor, parent_descriptor)
    if containment_error is not None:
        return SafeWriteResult(
            SafeWriteStatus.UNSAFE,
            destination,
            0,
            containment_error,
        )
    unsafe_destination = destination_error(parent_descriptor, name)
    if unsafe_destination is not None:
        return SafeWriteResult(
            SafeWriteStatus.UNSAFE,
            destination,
            0,
            unsafe_destination,
        )
    try:
        file_descriptor, temporary_name = open_staged_file(parent_descriptor)
    except OSError as exc:
        return SafeWriteResult(
            _open_failure_status(exc),
            destination,
            0,
            str(exc),
        )
    staged_identity = _identity(file_descriptor)
    try:
        try:
            containment_error = _containment_error(root_descriptor, parent_descriptor)
            if containment_error is not None:
                return discard_file(
                    parent_descriptor,
                    temporary_name,
                    destination,
                    SafeWriteStatus.UNSAFE,
                    containment_error,
                )
            try:
                with os.fdopen(file_descriptor, "wb", closefd=False) as handle:
                    _ = handle.write(data)
            except OSError as exc:
                return discard_file(
                    parent_descriptor,
                    temporary_name,
                    destination,
                    SafeWriteStatus.FAILED,
                    str(exc),
                )
            containment_error = _containment_error(root_descriptor, parent_descriptor)
            if containment_error is not None:
                return discard_file(
                    parent_descriptor,
                    temporary_name,
                    destination,
                    SafeWriteStatus.UNSAFE,
                    containment_error,
                )
        finally:
            os.close(file_descriptor)
        publication_error = publish_staged_file(
            parent_descriptor,
            temporary_name,
            name,
            destination,
            lambda: _containment_error(root_descriptor, parent_descriptor),
            _open_failure_status,
        )
        if publication_error is not None:
            return publication_error
        return SafeWriteResult(SafeWriteStatus.WRITTEN, destination, len(data))
    finally:
        remove_owned_staged_file(
            parent_descriptor,
            temporary_name,
            staged_identity,
        )


def _containment_error(root_descriptor: int, parent_descriptor: int) -> str | None:
    try:
        if _is_descendant(parent_descriptor, _identity(root_descriptor)):
            return None
    except OSError as exc:
        return f"could not verify parent ancestry: {exc}"
    return "output parent moved outside root"


def _is_descendant(descriptor: int, root_identity: tuple[int, int]) -> bool:
    current_descriptor = descriptor
    current_identity = _identity(current_descriptor)
    with ExitStack() as ancestors:
        while current_identity != root_identity:
            ancestor_descriptor = os.open(
                "..",
                _DIRECTORY_OPEN_FLAGS,
                dir_fd=current_descriptor,
            )
            _ = ancestors.callback(os.close, ancestor_descriptor)
            ancestor_identity = _identity(ancestor_descriptor)
            if ancestor_identity == current_identity:
                return False
            current_descriptor = ancestor_descriptor
            current_identity = ancestor_identity
    return True


def _identity(descriptor: int) -> tuple[int, int]:
    details = os.fstat(descriptor)
    return details.st_dev, details.st_ino


def _open_or_create_directory(parent_descriptor: int, name: str) -> int:
    try:
        return os.open(
            name,
            _DIRECTORY_OPEN_FLAGS,
            dir_fd=parent_descriptor,
        )
    except FileNotFoundError:
        try:
            os.mkdir(name, 0o700, dir_fd=parent_descriptor)
        except FileExistsError:
            return os.open(
                name,
                _DIRECTORY_OPEN_FLAGS,
                dir_fd=parent_descriptor,
            )
        return os.open(
            name,
            _DIRECTORY_OPEN_FLAGS,
            dir_fd=parent_descriptor,
        )


def _open_failure_status(exc: OSError) -> SafeWriteStatus:
    if exc.errno in _UNSAFE_OPEN_ERRNOS:
        return SafeWriteStatus.UNSAFE
    return SafeWriteStatus.FAILED
