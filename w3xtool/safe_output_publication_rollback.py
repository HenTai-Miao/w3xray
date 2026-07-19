"""Prior-output claims and identity-gated publication rollback."""

from __future__ import annotations

from .durable_io import sync_directory_descriptor
from .safe_output_models import SafeWriteResult, SafeWriteStatus
from .safe_output_cleanup import remove_owned_name
from .safe_output_publication_identity import (
    FileIdentity,
    claim_name,
    object_identity,
    private_name,
    regular_identity,
    restore_claim,
)


def claim_previous(
    parent_descriptor: int,
    destination_name: str,
    previous: FileIdentity | None,
) -> str | None:
    """Move a prior destination to a proved private identity claim."""
    if previous is None:
        return None
    backup_name = private_name("w3xray-backup")
    try:
        claim_name(
            parent_descriptor,
            destination_name,
            backup_name,
            previous,
        )
    except OSError:
        if object_identity(parent_descriptor, backup_name) is not None:
            _ = restore_claim(
                parent_descriptor,
                backup_name,
                destination_name,
                previous,
            )
        raise
    return backup_name


def rollback_published(
    parent_descriptor: int,
    destination_name: str,
    staged_identity: FileIdentity,
    backup_name: str | None,
    previous: FileIdentity | None,
    destination: str,
    status: SafeWriteStatus,
    reason: str,
) -> SafeWriteResult:
    """Remove only the published inode and never replace a concurrent name."""
    try:
        current = regular_identity(parent_descriptor, destination_name)
    except OSError as exc:
        current = None
        reason = f"{reason}; final identity unavailable: {exc}"
    if current == staged_identity:
        reason = _claim_published_for_removal(
            parent_descriptor,
            destination_name,
            staged_identity,
            backup_name,
            previous,
            reason,
        )
    elif current is None:
        reason = restore_previous(
            parent_descriptor,
            destination_name,
            backup_name,
            previous,
            reason,
        )
    else:
        reason = f"{reason}; concurrent destination preserved"
        reason = recovery_reason(
            parent_descriptor,
            backup_name,
            previous,
            reason,
        )
    try:
        sync_directory_descriptor(parent_descriptor)
    except OSError as exc:
        reason = f"{reason}; rollback sync failed: {exc}"
    return SafeWriteResult(status, destination, 0, reason)


def restore_previous(
    parent_descriptor: int,
    destination_name: str,
    backup_name: str | None,
    previous: FileIdentity | None,
    reason: str,
) -> str:
    """Restore a previous claim only when the public name remains absent."""
    if backup_name is None or previous is None:
        return reason
    try:
        claimed = regular_identity(parent_descriptor, backup_name)
    except OSError as exc:
        return f"{reason}; previous output claim unproved: {exc}"
    if claimed != previous:
        return f"{reason}; previous output claim changed"
    restore_error = restore_claim(
        parent_descriptor,
        backup_name,
        destination_name,
        previous,
    )
    if restore_error is not None:
        return recovery_reason(
            parent_descriptor,
            backup_name,
            previous,
            f"{reason}; previous restore failed: {restore_error}",
        )
    return reason


def _claim_published_for_removal(
    parent_descriptor: int,
    destination_name: str,
    staged_identity: FileIdentity,
    backup_name: str | None,
    previous: FileIdentity | None,
    reason: str,
) -> str:
    rollback_name = private_name("w3xray-rollback")
    try:
        claim_name(
            parent_descriptor,
            destination_name,
            rollback_name,
            staged_identity,
        )
    except OSError as exc:
        if object_identity(parent_descriptor, rollback_name) is not None:
            _ = restore_claim(
                parent_descriptor,
                rollback_name,
                destination_name,
                staged_identity,
            )
        return f"{reason}; rollback claim failed: {exc}"
    cleanup_error = remove_owned_name(
        parent_descriptor,
        rollback_name,
        staged_identity,
    )
    if cleanup_error is not None:
        reason = f"{reason}; rollback cleanup failed: {cleanup_error}"
    return restore_previous(
        parent_descriptor,
        destination_name,
        backup_name,
        previous,
        reason,
    )


def claim_displaced_previous(
    parent_descriptor: int,
    staged_name: str,
    backup_name: str,
    previous: FileIdentity,
) -> None:
    """Move an exchanged previous output to its expected private backup."""
    try:
        claim_name(parent_descriptor, staged_name, backup_name, previous)
    except OSError:
        if object_identity(parent_descriptor, backup_name) is not None:
            _ = restore_claim(
                parent_descriptor,
                backup_name,
                staged_name,
                previous,
            )
        raise


def recovery_reason(
    parent_descriptor: int,
    backup_name: str | None,
    previous: FileIdentity | None,
    reason: str,
) -> str:
    if backup_name is None or previous is None:
        return reason
    try:
        retained = regular_identity(parent_descriptor, backup_name)
    except OSError as exc:
        return f"{reason}; previous output recovery unproved: {exc}"
    if retained != previous:
        return f"{reason}; previous output recovery identity changed"
    return f"{reason}; previous output retained at {backup_name}"


__all__ = (
    "claim_displaced_previous",
    "claim_previous",
    "recovery_reason",
    "restore_previous",
    "rollback_published",
)
