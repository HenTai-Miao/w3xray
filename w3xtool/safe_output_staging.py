"""Temporary-file staging primitives for anchored output writes."""

from __future__ import annotations

import errno
import os
import secrets
import stat
from typing import Final

from w3xtool.descriptor_open_flags import staged_create_flags
from w3xtool.safe_output_models import SafeWriteResult, SafeWriteStatus
from w3xtool.safe_output_cleanup import remove_owned_name


_TEMP_NAME_ATTEMPTS: Final = 16


def open_staged_file(parent_descriptor: int) -> tuple[int, str]:
    """Create a unique no-follow temporary file below a held parent fd."""
    for _ in range(_TEMP_NAME_ATTEMPTS):
        name = f".w3xray-stage-{secrets.token_hex(16)}.tmp"
        try:
            descriptor = os.open(
                name,
                staged_create_flags(),
                0o600,
                dir_fd=parent_descriptor,
            )
        except FileExistsError:
            continue
        return descriptor, name
    raise FileExistsError(errno.EEXIST, "could not allocate temporary output")


def destination_error(parent_descriptor: int, name: str) -> str | None:
    """Return why an existing destination cannot be atomically replaced."""
    try:
        details = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError as exc:
        return f"could not inspect destination: {exc}"
    if stat.S_ISREG(details.st_mode):
        return None
    return "unsafe destination"


def discard_file(
    parent_descriptor: int,
    name: str,
    identity: tuple[int, int],
    destination: str,
    status: SafeWriteStatus,
    reason: str,
) -> SafeWriteResult:
    """Remove a staged file and preserve result context."""
    cleanup_error = remove_owned_name(parent_descriptor, name, identity)
    if cleanup_error is not None:
        reason = f"{reason}; cleanup failed: {cleanup_error}"
    return SafeWriteResult(status, destination, 0, reason)


def remove_owned_staged_file(
    parent_descriptor: int,
    name: str,
    identity: tuple[int, int],
) -> None:
    """Remove a leftover stage only when its inode still matches this write."""
    _ = remove_owned_name(parent_descriptor, name, identity)
