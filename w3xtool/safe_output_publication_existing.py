"""Continuous-name publication over one existing regular output."""

from __future__ import annotations

from collections.abc import Callable
import errno

from .atomic_rename import rename_exchange
from .durable_io import sync_directory_descriptor as rollback_sync
from .safe_output_models import SafeWriteResult, SafeWriteStatus
from .safe_output_publication_displaced import (
    claim_displaced_previous,
    locate_displaced,
)
from .safe_output_publication_existing_finish import (
    finish_publication,
    rollback_or_unproved,
    rollback_result,
)
from .safe_output_publication_identity import (
    FileIdentity,
    PublicationIdentityError,
    object_identity,
    private_name,
    regular_identity,
)
from .safe_output_publication_states import DisplacedAtBackup, DisplacedAtStage
from .safe_output_staging import discard_file


type _ContainmentCheck = Callable[[], str | None]
type _FailureStatus = Callable[[OSError], SafeWriteStatus]
type _DirectorySync = Callable[[int], None]


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
    """Exchange a complete stage and carry the displaced state explicitly."""
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
    except OSError as exc:
        displaced = _post_exchange_state(
            parent_descriptor,
            destination_name,
            staged_name,
            staged_identity,
        )
        if displaced is not None:
            return rollback_result(
                parent_descriptor,
                destination_name,
                staged_name,
                staged_identity,
                displaced,
                destination,
                _status(exc, failure_status),
                str(exc),
                rollback_sync,
            )
        return discard_file(
            parent_descriptor,
            staged_name,
            staged_identity,
            destination,
            _status(exc, failure_status),
            str(exc),
        )
    displaced = _post_exchange_state(
        parent_descriptor,
        destination_name,
        staged_name,
        staged_identity,
    )
    if displaced is None:
        return SafeWriteResult(
            SafeWriteStatus.UNSAFE,
            destination,
            0,
            "exchange result identity unavailable; recovery path unproved",
        )
    if displaced.expected != previous:
        return rollback_result(
            parent_descriptor,
            destination_name,
            staged_name,
            staged_identity,
            displaced,
            destination,
            SafeWriteStatus.UNSAFE,
            "previous output identity changed before exchange",
            rollback_sync,
        )
    return _claim_backup_and_finish(
        parent_descriptor,
        destination_name,
        staged_name,
        staged_identity,
        displaced,
        backup_name,
        destination,
        check_containment,
        failure_status,
        sync_directory,
    )


def _claim_backup_and_finish(
    parent_descriptor: int,
    destination_name: str,
    staged_name: str,
    staged_identity: FileIdentity,
    displaced: DisplacedAtStage,
    backup_name: str,
    destination: str,
    check_containment: _ContainmentCheck,
    failure_status: _FailureStatus,
    sync_directory: _DirectorySync,
) -> SafeWriteResult | None:
    try:
        claim = claim_displaced_previous(
            parent_descriptor,
            displaced,
            backup_name,
        )
    except OSError as exc:
        current = locate_displaced(
            parent_descriptor,
            staged_name,
            backup_name,
            displaced.expected,
        )
        return rollback_or_unproved(
            parent_descriptor,
            destination_name,
            staged_name,
            staged_identity,
            current,
            destination,
            _status(exc, failure_status),
            str(exc),
        )
    if claim.error is not None:
        return rollback_or_unproved(
            parent_descriptor,
            destination_name,
            staged_name,
            staged_identity,
            claim.state,
            destination,
            _status(claim.error, failure_status),
            str(claim.error),
        )
    if not isinstance(claim.state, DisplacedAtBackup):
        return rollback_or_unproved(
            parent_descriptor,
            destination_name,
            staged_name,
            staged_identity,
            claim.state,
            destination,
            SafeWriteStatus.UNSAFE,
            "backup claim state unproved",
        )
    return finish_publication(
        parent_descriptor,
        destination_name,
        staged_name,
        staged_identity,
        claim.state,
        destination,
        check_containment,
        sync_directory,
    )


def _post_exchange_state(
    parent_descriptor: int,
    destination_name: str,
    staged_name: str,
    staged_identity: FileIdentity,
) -> DisplacedAtStage | None:
    try:
        if regular_identity(parent_descriptor, destination_name) != staged_identity:
            return None
        displaced = object_identity(parent_descriptor, staged_name)
    except OSError:
        return None
    return None if displaced is None else DisplacedAtStage(staged_name, displaced)


def _require_identity(
    parent_descriptor: int,
    name: str,
    expected: FileIdentity,
    role: str,
) -> None:
    if regular_identity(parent_descriptor, name) != expected:
        raise PublicationIdentityError(f"{role} output identity changed")


def _status(exc: OSError, failure_status: _FailureStatus) -> SafeWriteStatus:
    if isinstance(exc, PublicationIdentityError) or exc.errno in {
        errno.EEXIST,
        errno.EBUSY,
    }:
        return SafeWriteStatus.UNSAFE
    return failure_status(exc)


__all__ = ("publish_over_existing",)
