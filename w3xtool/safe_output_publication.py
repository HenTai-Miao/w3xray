"""Identity-owned atomic publication for descriptor-anchored outputs."""

from __future__ import annotations

from collections.abc import Callable
import errno

from .durable_io import sync_directory_descriptor
from .safe_output_models import SafeWriteResult, SafeWriteStatus
from .safe_output_publication_identity import (
    FileIdentity,
    PublicationIdentityError,
    claim_name,
    regular_identity,
    remove_owned_name,
)
from .safe_output_publication_rollback import (
    claim_previous,
    restore_previous,
    rollback_published,
)
from .safe_output_staging import discard_file


_ContainmentCheck = Callable[[], str | None]
_FailureStatus = Callable[[OSError], SafeWriteStatus]


def publish_staged_file(
    parent_descriptor: int,
    staged_name: str,
    staged_identity: FileIdentity,
    destination_name: str,
    destination: str,
    check_containment: _ContainmentCheck,
    failure_status: _FailureStatus,
) -> SafeWriteResult | None:
    """Publish only while prior, staged, and final names retain ownership."""
    try:
        if regular_identity(parent_descriptor, staged_name) != staged_identity:
            raise PublicationIdentityError("staged output identity changed")
        previous = regular_identity(parent_descriptor, destination_name)
        backup_name = claim_previous(
            parent_descriptor,
            destination_name,
            previous,
        )
    except OSError as exc:
        return _discard_stage(
            parent_descriptor,
            staged_name,
            staged_identity,
            destination,
            _status(exc, failure_status),
            str(exc),
        )
    if backup_name is not None:
        try:
            sync_directory_descriptor(parent_descriptor)
        except OSError as exc:
            reason = restore_previous(
                parent_descriptor,
                destination_name,
                backup_name,
                previous,
                str(exc),
            )
            try:
                sync_directory_descriptor(parent_descriptor)
            except OSError as restore_exc:
                reason = f"{reason}; restore sync failed: {restore_exc}"
            return _discard_stage(
                parent_descriptor,
                staged_name,
                staged_identity,
                destination,
                SafeWriteStatus.FAILED,
                reason,
            )
    containment_error = check_containment()
    if containment_error is not None:
        reason = restore_previous(
            parent_descriptor,
            destination_name,
            backup_name,
            previous,
            containment_error,
        )
        return _discard_stage(
            parent_descriptor,
            staged_name,
            staged_identity,
            destination,
            SafeWriteStatus.UNSAFE,
            reason,
        )
    try:
        claim_name(
            parent_descriptor,
            staged_name,
            destination_name,
            staged_identity,
        )
    except OSError as exc:
        reason = restore_previous(
            parent_descriptor,
            destination_name,
            backup_name,
            previous,
            str(exc),
        )
        return _discard_stage(
            parent_descriptor,
            staged_name,
            staged_identity,
            destination,
            _status(exc, failure_status),
            reason,
        )
    containment_error = check_containment()
    identity_error = _final_identity_error(
        parent_descriptor,
        destination_name,
        staged_identity,
    )
    if containment_error is not None or identity_error is not None:
        reason = containment_error or identity_error or "unsafe publication"
        return rollback_published(
            parent_descriptor,
            destination_name,
            staged_identity,
            backup_name,
            previous,
            destination,
            SafeWriteStatus.UNSAFE,
            reason,
        )
    try:
        sync_directory_descriptor(parent_descriptor)
    except OSError as exc:
        return rollback_published(
            parent_descriptor,
            destination_name,
            staged_identity,
            backup_name,
            previous,
            destination,
            SafeWriteStatus.FAILED,
            str(exc),
        )
    identity_error = _final_identity_error(
        parent_descriptor,
        destination_name,
        staged_identity,
    )
    if identity_error is not None:
        return rollback_published(
            parent_descriptor,
            destination_name,
            staged_identity,
            backup_name,
            previous,
            destination,
            SafeWriteStatus.UNSAFE,
            identity_error,
        )
    if backup_name is not None and previous is not None:
        cleanup_error = remove_owned_name(
            parent_descriptor,
            backup_name,
            previous,
        )
        if cleanup_error is not None:
            return rollback_published(
                parent_descriptor,
                destination_name,
                staged_identity,
                backup_name,
                previous,
                destination,
                SafeWriteStatus.FAILED,
                cleanup_error,
            )
        try:
            sync_directory_descriptor(parent_descriptor)
        except OSError as exc:
            return SafeWriteResult(
                SafeWriteStatus.FAILED,
                destination,
                0,
                str(exc),
            )
    identity_error = _final_identity_error(
        parent_descriptor,
        destination_name,
        staged_identity,
    )
    if identity_error is not None:
        return SafeWriteResult(
            SafeWriteStatus.UNSAFE,
            destination,
            0,
            identity_error,
        )
    return None


def _discard_stage(
    parent_descriptor: int,
    staged_name: str,
    staged_identity: FileIdentity,
    destination: str,
    status: SafeWriteStatus,
    reason: str,
) -> SafeWriteResult:
    return discard_file(
        parent_descriptor,
        staged_name,
        staged_identity,
        destination,
        status,
        reason,
    )


def _final_identity_error(
    parent_descriptor: int,
    destination_name: str,
    staged_identity: FileIdentity,
) -> str | None:
    try:
        current = regular_identity(parent_descriptor, destination_name)
    except OSError as exc:
        return str(exc)
    if current != staged_identity:
        return "published output identity changed"
    return None


def _status(exc: OSError, failure_status: _FailureStatus) -> SafeWriteStatus:
    if isinstance(exc, PublicationIdentityError) or exc.errno in {
        errno.EEXIST,
        errno.EBUSY,
    }:
        return SafeWriteStatus.UNSAFE
    return failure_status(exc)


__all__ = ("publish_staged_file",)
