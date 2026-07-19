"""Rollback for continuous-name exchange publication."""

from __future__ import annotations

from collections.abc import Callable

from .atomic_rename import rename_exchange
from .safe_output_models import SafeWriteResult, SafeWriteStatus
from .safe_output_publication_identity import (
    FileIdentity,
    claim_name,
    regular_identity,
    remove_owned_name,
    restore_claim,
)
from .safe_output_publication_rollback import recovery_reason, restore_previous


def rollback_exchanged(
    parent_descriptor: int,
    destination_name: str,
    staged_name: str,
    staged_identity: FileIdentity,
    backup_name: str,
    previous: FileIdentity,
    destination: str,
    status: SafeWriteStatus,
    reason: str,
    sync_directory: Callable[[int], None],
) -> SafeWriteResult:
    """Restore an exchanged output while keeping the public name continuously bound."""
    try:
        current = regular_identity(parent_descriptor, destination_name)
    except OSError as exc:
        current = None
        reason = f"{reason}; final identity unavailable: {exc}"
    if current == staged_identity:
        reason = _restore_exchanged(
            parent_descriptor,
            destination_name,
            staged_name,
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
        sync_directory(parent_descriptor)
    except OSError as exc:
        reason = f"{reason}; rollback sync failed: {exc}"
    return SafeWriteResult(status, destination, 0, reason)


def _restore_exchanged(
    parent_descriptor: int,
    destination_name: str,
    staged_name: str,
    staged_identity: FileIdentity,
    backup_name: str,
    previous: FileIdentity,
    reason: str,
) -> str:
    restore_error = restore_claim(
        parent_descriptor,
        backup_name,
        staged_name,
        previous,
    )
    if restore_error is not None:
        return recovery_reason(
            parent_descriptor,
            backup_name,
            previous,
            f"{reason}; previous restore claim failed: {restore_error}",
        )
    try:
        if regular_identity(parent_descriptor, destination_name) != staged_identity:
            raise OSError("published output identity changed before exchange rollback")
        if regular_identity(parent_descriptor, staged_name) != previous:
            raise OSError("previous output identity changed before exchange rollback")
        rename_exchange(
            parent_descriptor,
            staged_name,
            parent_descriptor,
            destination_name,
        )
    except OSError as exc:
        reason = f"{reason}; exchange rollback failed: {exc}"
        try:
            claim_name(parent_descriptor, staged_name, backup_name, previous)
        except OSError as retain_exc:
            reason = f"{reason}; previous retention failed: {retain_exc}"
        return recovery_reason(
            parent_descriptor,
            backup_name,
            previous,
            reason,
        )
    cleanup_error = remove_owned_name(
        parent_descriptor,
        staged_name,
        staged_identity,
    )
    if cleanup_error is not None:
        return f"{reason}; rollback cleanup failed: {cleanup_error}"
    return reason


__all__ = ("rollback_exchanged",)
