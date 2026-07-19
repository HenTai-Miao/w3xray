"""Identity-safe cleanup inside held transaction-owned directory namespaces."""

from __future__ import annotations

import os
import secrets

from .descriptor_open_flags import directory_read_flags
from . import safe_output_publication_identity as identity_api
from .safe_output_cleanup_recovery import (
    directory_recovery,
    file_identity,
    find_retained,
    require_cleanup_directory,
    retained_recovery_reason,
    unopened_recovery,
)
from .safe_output_publication_states import (
    CleanupOutcome,
    CleanupRetained,
    NamedDisplacedState,
)


def cleanup_owned_state(
    parent_descriptor: int,
    state: NamedDisplacedState,
) -> CleanupOutcome:
    """Consume an owned name inside an isolated same-filesystem namespace."""
    directory_name = f".w3xray-cleanup-{secrets.token_hex(16)}.tmp"
    leaf_name = ".w3xray-cleanup-owned.tmp"
    try:
        os.mkdir(directory_name, 0o700, dir_fd=parent_descriptor)
        cleanup_descriptor = os.open(
            directory_name,
            directory_read_flags(),
            dir_fd=parent_descriptor,
        )
    except OSError as exc:
        recovery = unopened_recovery(parent_descriptor, directory_name)
        try:
            original_current = (
                identity_api.object_identity(parent_descriptor, state.name)
                == state.expected
            )
        except OSError:
            original_current = False
        current = state if original_current else None
        return CleanupOutcome(
            current,
            f"cleanup namespace setup failed: {exc}; {recovery}",
        )
    directory_identity = file_identity(os.fstat(cleanup_descriptor))
    try:
        require_cleanup_directory(
            parent_descriptor,
            directory_name,
            cleanup_descriptor,
            directory_identity,
        )
        try:
            identity_api.claim_name(
                parent_descriptor,
                state.name,
                leaf_name,
                state.expected,
                claimed_parent_descriptor=cleanup_descriptor,
            )
        except FileNotFoundError:
            return _finish_removed(
                parent_descriptor,
                cleanup_descriptor,
                directory_name,
                directory_identity,
            )
        except OSError as exc:
            retained = find_retained(
                cleanup_descriptor,
                directory_name,
                directory_identity,
                state.expected,
            )
            return _failure(
                parent_descriptor,
                cleanup_descriptor,
                state,
                retained,
                f"cleanup claim failed: {exc}",
            )
        if (
            identity_api.regular_identity(cleanup_descriptor, leaf_name)
            != state.expected
        ):
            retained = find_retained(
                cleanup_descriptor,
                directory_name,
                directory_identity,
                state.expected,
            )
            return _failure(
                parent_descriptor,
                cleanup_descriptor,
                state,
                retained,
                "cleanup identity changed after isolated claim",
            )
        try:
            os.unlink(leaf_name, dir_fd=cleanup_descriptor)
        except OSError as exc:
            retained = find_retained(
                cleanup_descriptor,
                directory_name,
                directory_identity,
                state.expected,
            )
            return _failure(
                parent_descriptor,
                cleanup_descriptor,
                state,
                retained,
                f"cleanup unlink failed: {exc}",
            )
        return _finish_removed(
            parent_descriptor,
            cleanup_descriptor,
            directory_name,
            directory_identity,
        )
    except OSError as exc:
        retained = find_retained(
            cleanup_descriptor,
            directory_name,
            directory_identity,
            state.expected,
        )
        return _failure(
            parent_descriptor,
            cleanup_descriptor,
            state,
            retained,
            f"cleanup proof failed: {exc}",
        )
    finally:
        os.close(cleanup_descriptor)


def remove_owned_name(
    parent_descriptor: int,
    name: str,
    expected: tuple[int, int],
) -> str | None:
    """Compatibility adapter for callers that only consume diagnostics."""
    from .safe_output_publication_states import DisplacedAtStage

    outcome = cleanup_owned_state(
        parent_descriptor,
        DisplacedAtStage(name, expected),
    )
    return outcome.error


def _finish_removed(
    parent_descriptor: int,
    cleanup_descriptor: int,
    directory_name: str,
    directory_identity: tuple[int, int],
) -> CleanupOutcome:
    try:
        if os.listdir(cleanup_descriptor):
            raise OSError("cleanup namespace contains an unexpected replacement")
        require_cleanup_directory(
            parent_descriptor,
            directory_name,
            cleanup_descriptor,
            directory_identity,
        )
        os.rmdir(directory_name, dir_fd=parent_descriptor)
    except OSError as exc:
        recovery = directory_recovery(
            parent_descriptor,
            directory_name,
            cleanup_descriptor,
            directory_identity,
        )
        return CleanupOutcome(
            None, f"cleanup namespace removal failed: {exc}; {recovery}"
        )
    return CleanupOutcome(None, None)


def _failure(
    parent_descriptor: int,
    cleanup_descriptor: int,
    original: NamedDisplacedState,
    retained: CleanupRetained | None,
    reason: str,
) -> CleanupOutcome:
    if retained is None:
        try:
            original_current = (
                identity_api.object_identity(parent_descriptor, original.name)
                == original.expected
            )
        except OSError:
            original_current = False
        if original_current:
            return CleanupOutcome(original, f"{reason}; cleanup source retained")
        return CleanupOutcome(None, f"{reason}; recovery path unproved")
    proved = retained_recovery_reason(parent_descriptor, retained, reason)
    if proved.endswith("recovery path unproved"):
        return CleanupOutcome(None, proved)
    return CleanupOutcome(retained, proved)


__all__ = ("cleanup_owned_state", "remove_owned_name", "retained_recovery_reason")
