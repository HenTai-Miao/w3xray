"""Stateful rollback for continuous-name exchange publication."""

from __future__ import annotations

from .atomic_rename import rename_exchange
from .safe_output_cleanup import cleanup_owned_state
from .safe_output_publication_displaced import (
    displaced_recovery_reason,
    restore_displaced_to_stage,
)
from .safe_output_publication_identity import object_identity
from .safe_output_publication_states import (
    DisplacedAtStage,
    DisplacedOutcome,
    DisplacedState,
)


def rollback_exchanged(
    parent_descriptor: int,
    destination_name: str,
    staged_name: str,
    staged_identity: tuple[int, int],
    displaced: DisplacedState,
    reason: str,
) -> DisplacedOutcome:
    """Consume a displaced state and restore the safest public identity."""
    try:
        current = object_identity(parent_descriptor, destination_name)
    except OSError as exc:
        current = None
        reason = f"{reason}; final identity unavailable: {exc}"
    if current == staged_identity:
        prepared = restore_displaced_to_stage(
            parent_descriptor,
            displaced,
            staged_name,
        )
        if prepared.error is not None:
            reason = f"{reason}; {prepared.error}"
        if not isinstance(prepared.state, DisplacedAtStage):
            return DisplacedOutcome(
                prepared.state,
                displaced_recovery_reason(
                    parent_descriptor,
                    prepared.state,
                    reason,
                ),
            )
        return _restore_exchange(
            parent_descriptor,
            destination_name,
            staged_name,
            staged_identity,
            prepared.state,
            reason,
        )
    if current is None:
        prepared = restore_displaced_to_stage(
            parent_descriptor,
            displaced,
            staged_name,
        )
        if not isinstance(prepared.state, DisplacedAtStage):
            return DisplacedOutcome(
                prepared.state,
                displaced_recovery_reason(
                    parent_descriptor,
                    prepared.state,
                    f"{reason}; public destination remained absent",
                ),
            )
        from .safe_output_publication_identity import restore_claim

        restore_error = restore_claim(
            parent_descriptor,
            prepared.state.name,
            destination_name,
            prepared.state.expected,
        )
        if restore_error is None:
            return DisplacedOutcome(None, prepared.error or reason)
        return DisplacedOutcome(
            prepared.state,
            displaced_recovery_reason(
                parent_descriptor,
                prepared.state,
                f"{reason}; previous restore failed: {restore_error}",
            ),
        )
    return DisplacedOutcome(
        displaced,
        displaced_recovery_reason(
            parent_descriptor,
            displaced,
            f"{reason}; concurrent destination preserved",
        ),
    )


def _restore_exchange(
    parent_descriptor: int,
    destination_name: str,
    staged_name: str,
    staged_identity: tuple[int, int],
    displaced: DisplacedAtStage,
    reason: str,
) -> DisplacedOutcome:
    try:
        if object_identity(parent_descriptor, destination_name) != staged_identity:
            raise OSError("published output identity changed before exchange rollback")
        if object_identity(parent_descriptor, staged_name) != displaced.expected:
            raise OSError("displaced output identity changed before exchange rollback")
        rename_exchange(
            parent_descriptor,
            staged_name,
            parent_descriptor,
            destination_name,
        )
    except OSError as exc:
        return DisplacedOutcome(
            displaced,
            displaced_recovery_reason(
                parent_descriptor,
                displaced,
                f"{reason}; exchange rollback failed: {exc}",
            ),
        )
    restored = object_identity(parent_descriptor, destination_name)
    private = object_identity(parent_descriptor, staged_name)
    if restored == displaced.expected and private == staged_identity:
        cleanup = cleanup_owned_state(
            parent_descriptor,
            DisplacedAtStage(staged_name, staged_identity),
        )
        if cleanup.error is None:
            return DisplacedOutcome(None, reason)
        return DisplacedOutcome(
            cleanup.state,
            f"{reason}; rollback cleanup failed: {cleanup.error}",
        )
    return _reverse_mismatched_rollback(
        parent_descriptor,
        destination_name,
        staged_name,
        displaced,
        restored,
        private,
        reason,
    )


def _reverse_mismatched_rollback(
    parent_descriptor: int,
    destination_name: str,
    staged_name: str,
    displaced: DisplacedAtStage,
    restored: tuple[int, int] | None,
    private: tuple[int, int] | None,
    reason: str,
) -> DisplacedOutcome:
    if restored != displaced.expected or private is None:
        return DisplacedOutcome(
            None,
            f"{reason}; rollback exchange result unproved; recovery path unproved",
        )
    try:
        rename_exchange(
            parent_descriptor,
            staged_name,
            parent_descriptor,
            destination_name,
        )
    except OSError as exc:
        return DisplacedOutcome(
            None,
            f"{reason}; rollback mismatch reversal failed: {exc}; recovery path unproved",
        )
    current_public = object_identity(parent_descriptor, destination_name)
    current_displaced = object_identity(parent_descriptor, staged_name)
    successor = DisplacedAtStage(staged_name, displaced.expected)
    if current_public != private or current_displaced != displaced.expected:
        return DisplacedOutcome(
            None,
            f"{reason}; rollback mismatch reversal unproved; recovery path unproved",
        )
    return DisplacedOutcome(
        successor,
        displaced_recovery_reason(
            parent_descriptor,
            successor,
            f"{reason}; concurrent destination restored after rollback race",
            label="displaced output",
        ),
    )


__all__ = ("rollback_exchanged",)
