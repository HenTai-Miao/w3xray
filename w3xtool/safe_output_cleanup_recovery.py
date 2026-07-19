"""Proof and recovery reporting for isolated safe-output cleanup namespaces."""

from __future__ import annotations

import os
import stat

from .descriptor_open_flags import directory_read_flags
from . import safe_output_publication_identity as identity_api
from .safe_output_publication_states import CleanupRetained


type FileIdentity = tuple[int, int]


def retained_recovery_reason(
    parent_descriptor: int,
    retained: CleanupRetained,
    reason: str,
) -> str:
    """Name a nested recovery object only after proving both bindings."""
    try:
        descriptor = os.open(
            retained.directory_name,
            directory_read_flags(),
            dir_fd=parent_descriptor,
        )
    except OSError:
        return f"{reason}; recovery path unproved"
    try:
        require_cleanup_directory(
            parent_descriptor,
            retained.directory_name,
            descriptor,
            retained.directory_identity,
        )
        if (
            identity_api.regular_identity(descriptor, retained.leaf_name)
            != retained.expected
        ):
            return f"{reason}; recovery path unproved"
    except OSError:
        return f"{reason}; recovery path unproved"
    finally:
        os.close(descriptor)
    return f"{reason}; previous output retained at {retained.name}"


def find_retained(
    cleanup_descriptor: int,
    directory_name: str,
    directory_identity: FileIdentity,
    expected: FileIdentity,
) -> CleanupRetained | None:
    """Return the unique expected regular identity below a cleanup fd."""
    matches: list[str] = []
    try:
        for name in os.listdir(cleanup_descriptor):
            if identity_api.regular_identity(cleanup_descriptor, name) == expected:
                matches.append(name)
    except OSError:
        return None
    if len(matches) != 1:
        return None
    return CleanupRetained(
        directory_name,
        directory_identity,
        matches[0],
        expected,
    )


def require_cleanup_directory(
    parent_descriptor: int,
    directory_name: str,
    cleanup_descriptor: int,
    expected: FileIdentity,
) -> None:
    """Prove held and public directory bindings belong to this transaction."""
    held = os.fstat(cleanup_descriptor)
    named = os.stat(
        directory_name,
        dir_fd=parent_descriptor,
        follow_symlinks=False,
    )
    if (
        not stat.S_ISDIR(held.st_mode)
        or not stat.S_ISDIR(named.st_mode)
        or file_identity(held) != expected
        or file_identity(named) != expected
        or stat.S_IMODE(held.st_mode) != 0o700
        or held.st_uid != os.geteuid()
    ):
        raise OSError("cleanup directory identity changed")


def directory_recovery(
    parent_descriptor: int,
    directory_name: str,
    cleanup_descriptor: int,
    expected: FileIdentity,
) -> str:
    """Report an outer residue only while its transaction identity is proved."""
    try:
        require_cleanup_directory(
            parent_descriptor,
            directory_name,
            cleanup_descriptor,
            expected,
        )
    except OSError:
        return "recovery path unproved"
    return f"cleanup residue retained at {directory_name}"


def unopened_recovery(parent_descriptor: int, directory_name: str) -> str:
    """Never claim ownership for a setup name that was not descriptor-bound."""
    try:
        _ = os.stat(
            directory_name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return "no cleanup residue"
    except OSError:
        return "recovery path unproved"
    return "recovery path unproved"


def file_identity(details: os.stat_result) -> FileIdentity:
    """Return the device/inode pair used by cleanup state."""
    return details.st_dev, details.st_ino


__all__ = (
    "directory_recovery",
    "file_identity",
    "find_retained",
    "require_cleanup_directory",
    "retained_recovery_reason",
    "unopened_recovery",
)
