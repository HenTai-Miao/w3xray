"""State transitions for displaced safe-output publication objects."""

from __future__ import annotations

import os
import stat

from .descriptor_open_flags import directory_read_flags
from . import safe_output_publication_identity as identity_api
from .safe_output_cleanup_recovery import retained_recovery_reason
from .safe_output_publication_states import (
    BackupClaimOutcome,
    CleanupRetained,
    DisplacedAtBackup,
    DisplacedAtStage,
    DisplacedOutcome,
    DisplacedState,
)


def claim_displaced_previous(
    parent_descriptor: int,
    state: DisplacedAtStage,
    backup_name: str,
) -> BackupClaimOutcome:
    """Consume a stage state and return its proved backup successor."""
    try:
        identity_api.claim_name(
            parent_descriptor,
            state.name,
            backup_name,
            state.expected,
        )
    except OSError as exc:
        current = locate_displaced(
            parent_descriptor,
            state.name,
            backup_name,
            state.expected,
        )
        return BackupClaimOutcome(current, exc)
    return BackupClaimOutcome(
        DisplacedAtBackup(backup_name, state.expected),
        None,
    )


def locate_displaced(
    parent_descriptor: int,
    staged_name: str,
    backup_name: str,
    expected: tuple[int, int],
) -> DisplacedAtStage | DisplacedAtBackup | None:
    """Return the unique proved location for one expected displaced identity."""
    try:
        at_stage = identity_api.object_identity(parent_descriptor, staged_name)
        at_backup = identity_api.object_identity(parent_descriptor, backup_name)
    except OSError:
        return None
    matches = (
        (DisplacedAtStage(staged_name, expected) if at_stage == expected else None),
        (DisplacedAtBackup(backup_name, expected) if at_backup == expected else None),
    )
    proved = tuple(value for value in matches if value is not None)
    return proved[0] if len(proved) == 1 else None


def restore_displaced_to_stage(
    parent_descriptor: int,
    state: DisplacedState,
    staged_name: str,
) -> DisplacedOutcome:
    """Consume any private state and return a proved stage state."""
    if isinstance(state, DisplacedAtStage):
        if state.name == staged_name and _matches(parent_descriptor, state):
            return DisplacedOutcome(state, None)
        return DisplacedOutcome(state, "displaced stage identity changed")
    if isinstance(state, DisplacedAtBackup):
        error = identity_api.restore_claim(
            parent_descriptor,
            state.name,
            staged_name,
            state.expected,
        )
        if error is None:
            return DisplacedOutcome(
                DisplacedAtStage(staged_name, state.expected),
                None,
            )
        current = locate_displaced(
            parent_descriptor,
            staged_name,
            state.name,
            state.expected,
        )
        return DisplacedOutcome(current, f"previous restore claim failed: {error}")
    return _restore_cleanup_retained(parent_descriptor, state, staged_name)


def displaced_recovery_reason(
    parent_descriptor: int,
    state: DisplacedState | None,
    reason: str,
    *,
    label: str = "previous output",
) -> str:
    """Name a current recovery state only after re-proving it."""
    if state is None:
        return f"{reason}; recovery path unproved"
    if isinstance(state, CleanupRetained):
        return retained_recovery_reason(parent_descriptor, state, reason)
    if not _matches(parent_descriptor, state):
        return f"{reason}; recovery path unproved"
    return f"{reason}; {label} retained at {state.name}"


def _restore_cleanup_retained(
    parent_descriptor: int,
    state: CleanupRetained,
    staged_name: str,
) -> DisplacedOutcome:
    try:
        descriptor = os.open(
            state.directory_name,
            directory_read_flags(),
            dir_fd=parent_descriptor,
        )
    except OSError as exc:
        return DisplacedOutcome(state, f"cleanup recovery open failed: {exc}")
    try:
        if not _cleanup_binding_matches(parent_descriptor, descriptor, state):
            return DisplacedOutcome(state, "cleanup recovery path unproved")
        try:
            identity_api.claim_name(
                descriptor,
                state.leaf_name,
                staged_name,
                state.expected,
                claimed_parent_descriptor=parent_descriptor,
            )
        except OSError as exc:
            current: DisplacedState | None = (
                DisplacedAtStage(staged_name, state.expected)
                if identity_api.object_identity(parent_descriptor, staged_name)
                == state.expected
                else state
            )
            return DisplacedOutcome(current, f"cleanup recovery claim failed: {exc}")
        successor = DisplacedAtStage(staged_name, state.expected)
        cleanup_error = _remove_empty_cleanup_directory(
            parent_descriptor,
            descriptor,
            state,
        )
        return DisplacedOutcome(successor, cleanup_error)
    finally:
        os.close(descriptor)


def _remove_empty_cleanup_directory(
    parent_descriptor: int,
    descriptor: int,
    state: CleanupRetained,
) -> str | None:
    try:
        if os.listdir(descriptor):
            raise OSError("cleanup recovery directory is not empty")
        if not _cleanup_directory_matches(parent_descriptor, descriptor, state):
            raise OSError("cleanup recovery directory identity changed")
        os.rmdir(state.directory_name, dir_fd=parent_descriptor)
    except OSError as exc:
        return f"cleanup recovery directory retained: {exc}"
    return None


def _cleanup_binding_matches(
    parent_descriptor: int,
    descriptor: int,
    state: CleanupRetained,
) -> bool:
    return (
        _cleanup_directory_matches(
            parent_descriptor,
            descriptor,
            state,
        )
        and identity_api.regular_identity(descriptor, state.leaf_name) == state.expected
    )


def _cleanup_directory_matches(
    parent_descriptor: int,
    descriptor: int,
    state: CleanupRetained,
) -> bool:
    try:
        held = os.fstat(descriptor)
        named = os.stat(
            state.directory_name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
    except OSError:
        return False
    return (
        stat.S_ISDIR(held.st_mode)
        and stat.S_ISDIR(named.st_mode)
        and (held.st_dev, held.st_ino) == state.directory_identity
        and (named.st_dev, named.st_ino) == state.directory_identity
    )


def _matches(
    parent_descriptor: int,
    state: DisplacedAtStage | DisplacedAtBackup,
) -> bool:
    try:
        return (
            identity_api.object_identity(parent_descriptor, state.name)
            == state.expected
        )
    except OSError:
        return False


__all__ = (
    "claim_displaced_previous",
    "displaced_recovery_reason",
    "locate_displaced",
    "restore_displaced_to_stage",
)
