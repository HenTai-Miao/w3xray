"""Durability, cleanup, and rollback completion for existing-output writes."""

from __future__ import annotations

from collections.abc import Callable

from .durable_io import sync_directory_descriptor as rollback_sync
from .safe_output_cleanup import cleanup_owned_state
from .safe_output_models import SafeWriteResult, SafeWriteStatus
from .safe_output_publication_exchange_rollback import rollback_exchanged
from .safe_output_publication_identity import FileIdentity, regular_identity
from .safe_output_publication_states import DisplacedAtBackup, DisplacedState


type ContainmentCheck = Callable[[], str | None]
type DirectorySync = Callable[[int], None]


def finish_publication(
    parent_descriptor: int,
    destination_name: str,
    staged_name: str,
    staged_identity: FileIdentity,
    displaced: DisplacedAtBackup,
    destination: str,
    check_containment: ContainmentCheck,
    sync_directory: DirectorySync,
) -> SafeWriteResult | None:
    """Prove durability, consume the backup state, and finish publication."""
    for check_after_sync in (True, False):
        try:
            sync_directory(parent_descriptor)
        except OSError as exc:
            return rollback_result(
                parent_descriptor,
                destination_name,
                staged_name,
                staged_identity,
                displaced,
                destination,
                SafeWriteStatus.FAILED,
                str(exc),
                sync_directory,
            )
        error = _identity_error(parent_descriptor, destination_name, staged_identity)
        if check_after_sync:
            error = check_containment() or error
        if error is not None:
            return rollback_result(
                parent_descriptor,
                destination_name,
                staged_name,
                staged_identity,
                displaced,
                destination,
                SafeWriteStatus.UNSAFE,
                error,
                rollback_sync,
            )
    cleanup = cleanup_owned_state(parent_descriptor, displaced)
    if cleanup.error is not None:
        if cleanup.state is not None:
            return rollback_result(
                parent_descriptor,
                destination_name,
                staged_name,
                staged_identity,
                cleanup.state,
                destination,
                SafeWriteStatus.FAILED,
                cleanup.error,
                rollback_sync,
            )
        return SafeWriteResult(SafeWriteStatus.FAILED, destination, 0, cleanup.error)
    try:
        sync_directory(parent_descriptor)
    except OSError as exc:
        return SafeWriteResult(SafeWriteStatus.FAILED, destination, 0, str(exc))
    error = _identity_error(parent_descriptor, destination_name, staged_identity)
    if error is not None:
        return SafeWriteResult(SafeWriteStatus.UNSAFE, destination, 0, error)
    return None


def rollback_or_unproved(
    parent_descriptor: int,
    destination_name: str,
    staged_name: str,
    staged_identity: FileIdentity,
    displaced: DisplacedState | None,
    destination: str,
    status: SafeWriteStatus,
    reason: str,
) -> SafeWriteResult:
    """Rollback one proved state or truthfully report that none is known."""
    if displaced is None:
        return SafeWriteResult(
            status,
            destination,
            0,
            f"{reason}; displaced recovery path unproved",
        )
    return rollback_result(
        parent_descriptor,
        destination_name,
        staged_name,
        staged_identity,
        displaced,
        destination,
        status,
        reason,
        rollback_sync,
    )


def rollback_result(
    parent_descriptor: int,
    destination_name: str,
    staged_name: str,
    staged_identity: FileIdentity,
    displaced: DisplacedState,
    destination: str,
    status: SafeWriteStatus,
    reason: str,
    sync_directory: DirectorySync,
) -> SafeWriteResult:
    """Consume a rollback state, sync its successor, and format the result."""
    outcome = rollback_exchanged(
        parent_descriptor,
        destination_name,
        staged_name,
        staged_identity,
        displaced,
        reason,
    )
    detail = outcome.error or reason
    try:
        sync_directory(parent_descriptor)
    except OSError as exc:
        detail = f"{detail}; rollback sync failed: {exc}"
    return SafeWriteResult(status, destination, 0, detail)


def _identity_error(
    parent_descriptor: int,
    name: str,
    expected: FileIdentity,
) -> str | None:
    try:
        current = regular_identity(parent_descriptor, name)
    except OSError as exc:
        return str(exc)
    return None if current == expected else "published output identity changed"


__all__ = ("finish_publication", "rollback_or_unproved", "rollback_result")
