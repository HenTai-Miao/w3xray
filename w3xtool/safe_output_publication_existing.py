"""Continuous-name publication over one existing regular output."""

from __future__ import annotations

from collections.abc import Callable
import errno

from .atomic_rename import rename_exchange
from .durable_io import sync_directory_descriptor as _rollback_sync
from .safe_output_models import SafeWriteResult, SafeWriteStatus
from .safe_output_publication_identity import (
    FileIdentity,
    PublicationIdentityError,
    private_name,
    regular_identity,
    remove_owned_name,
)
from .safe_output_publication_exchange_rollback import rollback_exchanged
from .safe_output_publication_rollback import claim_displaced_previous
from .safe_output_staging import discard_file


_ContainmentCheck = Callable[[], str | None]
_FailureStatus = Callable[[OSError], SafeWriteStatus]
_DirectorySync = Callable[[int], None]


def publish_over_existing(
    parent_descriptor: int,
    staged_name: str,
    staged_identity: FileIdentity,
    destination_name: str,
    previous: FileIdentity,
    destination: str,
    check_containment: _ContainmentCheck,
    failure_status: _FailureStatus,
    sync_directory: _DirectorySync,
) -> SafeWriteResult | None:
    """Exchange a complete stage without ever unbinding the public name."""
    backup_name = private_name("w3xray-backup")
    try:
        _require_identity(parent_descriptor, staged_name, staged_identity, "staged")
        _require_identity(parent_descriptor, destination_name, previous, "previous")
        containment_error = check_containment()
        if containment_error is not None:
            return discard_file(
                parent_descriptor,
                staged_name,
                staged_identity,
                destination,
                SafeWriteStatus.UNSAFE,
                containment_error,
            )
        rename_exchange(
            parent_descriptor,
            staged_name,
            parent_descriptor,
            destination_name,
        )
        _require_identity(parent_descriptor, destination_name, staged_identity, "final")
        _require_identity(parent_descriptor, staged_name, previous, "previous")
        claim_displaced_previous(
            parent_descriptor,
            staged_name,
            backup_name,
            previous,
        )
    except OSError as exc:
        if _is_exchanged(parent_descriptor, destination_name, staged_identity):
            return _rollback(
                parent_descriptor,
                destination_name,
                staged_name,
                staged_identity,
                backup_name,
                previous,
                destination,
                _status(exc, failure_status),
                str(exc),
                _rollback_sync,
            )
        return discard_file(
            parent_descriptor,
            staged_name,
            staged_identity,
            destination,
            _status(exc, failure_status),
            str(exc),
        )
    try:
        sync_directory(parent_descriptor)
    except OSError as exc:
        return _rollback(
            parent_descriptor,
            destination_name,
            staged_name,
            staged_identity,
            backup_name,
            previous,
            destination,
            SafeWriteStatus.FAILED,
            str(exc),
            sync_directory,
        )
    error = check_containment() or _identity_error(
        parent_descriptor,
        destination_name,
        staged_identity,
    )
    if error is not None:
        return _rollback(
            parent_descriptor,
            destination_name,
            staged_name,
            staged_identity,
            backup_name,
            previous,
            destination,
            SafeWriteStatus.UNSAFE,
            error,
            _rollback_sync,
        )
    try:
        sync_directory(parent_descriptor)
    except OSError as exc:
        return _rollback(
            parent_descriptor,
            destination_name,
            staged_name,
            staged_identity,
            backup_name,
            previous,
            destination,
            SafeWriteStatus.FAILED,
            str(exc),
            _rollback_sync,
        )
    error = _identity_error(parent_descriptor, destination_name, staged_identity)
    if error is not None:
        return _rollback(
            parent_descriptor,
            destination_name,
            staged_name,
            staged_identity,
            backup_name,
            previous,
            destination,
            SafeWriteStatus.UNSAFE,
            error,
            _rollback_sync,
        )
    cleanup_error = remove_owned_name(parent_descriptor, backup_name, previous)
    if cleanup_error is not None:
        return _rollback(
            parent_descriptor,
            destination_name,
            staged_name,
            staged_identity,
            backup_name,
            previous,
            destination,
            SafeWriteStatus.FAILED,
            cleanup_error,
            _rollback_sync,
        )
    try:
        sync_directory(parent_descriptor)
    except OSError as exc:
        return SafeWriteResult(SafeWriteStatus.FAILED, destination, 0, str(exc))
    error = _identity_error(parent_descriptor, destination_name, staged_identity)
    if error is not None:
        return SafeWriteResult(SafeWriteStatus.UNSAFE, destination, 0, error)
    return None


def _rollback(
    parent_descriptor: int,
    destination_name: str,
    staged_name: str,
    staged_identity: FileIdentity,
    backup_name: str,
    previous: FileIdentity,
    destination: str,
    status: SafeWriteStatus,
    reason: str,
    sync_directory: _DirectorySync,
) -> SafeWriteResult:
    return rollback_exchanged(
        parent_descriptor,
        destination_name,
        staged_name,
        staged_identity,
        backup_name,
        previous,
        destination,
        status,
        reason,
        sync_directory,
    )


def _require_identity(
    parent_descriptor: int,
    name: str,
    expected: FileIdentity,
    role: str,
) -> None:
    if regular_identity(parent_descriptor, name) != expected:
        raise PublicationIdentityError(f"{role} output identity changed")


def _identity_error(
    parent_descriptor: int,
    name: str,
    expected: FileIdentity,
) -> str | None:
    try:
        _require_identity(parent_descriptor, name, expected, "published")
    except OSError as exc:
        return str(exc)
    return None


def _is_exchanged(
    parent_descriptor: int,
    destination_name: str,
    staged_identity: FileIdentity,
) -> bool:
    try:
        return regular_identity(parent_descriptor, destination_name) == staged_identity
    except OSError:
        return False


def _status(exc: OSError, failure_status: _FailureStatus) -> SafeWriteStatus:
    if isinstance(exc, PublicationIdentityError) or exc.errno in {
        errno.EEXIST,
        errno.EBUSY,
    }:
        return SafeWriteStatus.UNSAFE
    return failure_status(exc)


__all__ = ("publish_over_existing",)
