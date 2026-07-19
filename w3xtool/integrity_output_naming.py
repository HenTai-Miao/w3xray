"""Exact-parent filesystem naming behavior for integrity output leaves."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import errno
import os
import secrets
import stat
import unicodedata
from typing import final, override

from .description_cache_retained_siblings import (
    BACKUP_PREFIX,
    RETAINED_PREFIX,
    STAGE_PREFIX,
)
from .descriptor_open_flags import directory_read_flags, staged_create_flags


type _Identity = tuple[int, int]
type _NameKey = Callable[[str], str]
_RESERVED_PREFIXES = (RETAINED_PREFIX, STAGE_PREFIX, BACKUP_PREFIX)


@final
class IntegrityNamingProbeError(OSError):
    """The exact-parent naming behavior could not be safely established."""

    __slots__ = ("detail",)

    detail: str

    def __init__(self, detail: str) -> None:
        super().__init__(errno.EBUSY, detail)
        self.detail = detail

    @override
    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True, slots=True)
class FilesystemNamingBehavior:
    """Alias transformations proved inside the exact parent filesystem."""

    case_insensitive: bool
    normalization_insensitive: bool

    def key(self, value: str) -> str:
        """Apply only transformations this exact filesystem aliases."""
        normalized = (
            unicodedata.normalize("NFD", value)
            if self.normalization_insensitive
            else value
        )
        return normalized.casefold() if self.case_insensitive else normalized


def is_reserved_output_name(
    parent_descriptor: int,
    name: str,
    active_name: str,
) -> bool:
    """Reject exact reservations and only physically applicable aliases."""
    if _matches_reservation(name, active_name, _exact_key):
        return True
    if not _matches_reservation(name, active_name, _universal_key):
        return False
    behavior = probe_filesystem_naming(parent_descriptor)
    return _matches_reservation(name, active_name, behavior.key)


def probe_filesystem_naming(parent_descriptor: int) -> FilesystemNamingBehavior:
    """Probe naming aliases in a held mode-0700 directory on this filesystem."""
    directory_name = f".w3xray-name-probe-{secrets.token_hex(16)}.tmp"
    directory_created = False
    try:
        os.mkdir(directory_name, 0o700, dir_fd=parent_descriptor)
        directory_created = True
        descriptor = os.open(
            directory_name,
            directory_read_flags(),
            dir_fd=parent_descriptor,
        )
    except OSError as exc:
        cleanup = "probe recovery path unproved" if directory_created else None
        detail = f"filesystem naming probe setup failed: {exc}"
        raise IntegrityNamingProbeError(_with_cleanup(detail, cleanup)) from exc
    outer_identity = _identity(os.fstat(descriptor))
    leaves: dict[str, _Identity] = {}
    failure: OSError | None = None
    behavior: FilesystemNamingBehavior | None = None
    try:
        _require_outer_identity(parent_descriptor, directory_name, outer_identity)
        case_token = secrets.token_hex(8)
        case_insensitive = _probe_pair(
            descriptor,
            f"Case-{case_token}",
            f"case-{case_token}",
            leaves,
        )
        token = secrets.token_hex(8)
        normalization_insensitive = _probe_pair(
            descriptor,
            f"\u00e9-{token}",
            f"e\u0301-{token}",
            leaves,
        )
        behavior = FilesystemNamingBehavior(
            case_insensitive,
            normalization_insensitive,
        )
    except OSError as exc:
        failure = exc
    cleanup = _cleanup_probe(
        parent_descriptor,
        directory_name,
        outer_identity,
        descriptor,
        leaves,
    )
    os.close(descriptor)
    if failure is not None:
        detail = f"filesystem naming probe failed: {failure}"
        raise IntegrityNamingProbeError(_with_cleanup(detail, cleanup)) from failure
    if cleanup is not None:
        raise IntegrityNamingProbeError(
            f"filesystem naming probe cleanup failed; {cleanup}"
        )
    if behavior is None:
        raise IntegrityNamingProbeError("filesystem naming probe produced no result")
    return behavior


def _probe_pair(
    descriptor: int,
    primary: str,
    alternate: str,
    leaves: dict[str, _Identity],
) -> bool:
    file_descriptor = os.open(
        primary,
        staged_create_flags(),
        0o600,
        dir_fd=descriptor,
    )
    try:
        expected = _identity(os.fstat(file_descriptor))
    finally:
        os.close(file_descriptor)
    leaves[primary] = expected
    if _regular_identity(descriptor, primary) != expected:
        raise IntegrityNamingProbeError("filesystem naming probe identity changed")
    alternate_identity = _regular_identity(descriptor, alternate)
    if alternate_identity is None:
        return False
    if alternate_identity != expected:
        raise IntegrityNamingProbeError("filesystem naming probe alias was ambiguous")
    return True


def _cleanup_probe(
    parent_descriptor: int,
    directory_name: str,
    outer_identity: _Identity,
    descriptor: int,
    leaves: dict[str, _Identity],
) -> str | None:
    try:
        for name, expected in leaves.items():
            if _regular_identity(descriptor, name) != expected:
                raise IntegrityNamingProbeError("probe leaf identity changed")
            os.unlink(name, dir_fd=descriptor)
        if os.listdir(descriptor):
            raise IntegrityNamingProbeError("probe directory contains unknown leaves")
        _require_outer_identity(parent_descriptor, directory_name, outer_identity)
        os.rmdir(directory_name, dir_fd=parent_descriptor)
        return None
    except OSError:
        return _probe_recovery_path(
            parent_descriptor,
            directory_name,
            outer_identity,
            descriptor,
            leaves,
        )


def _probe_recovery_path(
    parent_descriptor: int,
    directory_name: str,
    outer_identity: _Identity,
    descriptor: int,
    leaves: dict[str, _Identity],
) -> str:
    try:
        _require_outer_identity(parent_descriptor, directory_name, outer_identity)
        for name, expected in leaves.items():
            if _regular_identity(descriptor, name) == expected:
                return f"probe residue retained at {directory_name}/{name}"
        if not os.listdir(descriptor):
            return f"probe residue retained at {directory_name}"
    except OSError:
        pass
    return "probe recovery path unproved"


def _require_outer_identity(
    parent_descriptor: int, name: str, expected: _Identity
) -> None:
    details = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    if not stat.S_ISDIR(details.st_mode) or _identity(details) != expected:
        raise IntegrityNamingProbeError("probe directory identity changed")


def _regular_identity(descriptor: int, name: str) -> _Identity | None:
    try:
        details = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(details.st_mode):
        raise IntegrityNamingProbeError("probe leaf is not a regular file")
    return _identity(details)


def _matches_reservation(name: str, active_name: str, key: _NameKey) -> bool:
    normalized = key(name)
    return normalized == key(active_name) or normalized.startswith(
        tuple(key(value) for value in _RESERVED_PREFIXES)
    )


def _exact_key(value: str) -> str:
    return value


def _universal_key(value: str) -> str:
    return unicodedata.normalize("NFD", value).casefold()


def _identity(details: os.stat_result) -> _Identity:
    return details.st_dev, details.st_ino


def _with_cleanup(detail: str, cleanup: str | None) -> str:
    return detail if cleanup is None else f"{detail}; {cleanup}"


__all__ = (
    "FilesystemNamingBehavior",
    "IntegrityNamingProbeError",
    "is_reserved_output_name",
    "probe_filesystem_naming",
)
