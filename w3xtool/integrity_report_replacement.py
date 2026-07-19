"""Proved exchange and immutable archival of one prior integrity report."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .atomic_rename import rename_exchange, rename_noreplace
from .durable_io import sync_directory_descriptor
from .integrity_report_history import INTEGRITY_HISTORY_REPORT_NAME
from .integrity_report_history_directory import (
    BoundIntegrityHistoryStage,
    require_history_generation_current,
    require_history_stage_current,
)
from .integrity_report_history_generation import (
    require_integrity_history_generation,
    write_integrity_history_generation,
)
from .integrity_report_publication_errors import (
    IntegrityFailureStatus,
    integrity_publication_failure,
    integrity_publication_status,
)
from .integrity_report_publication_models import (
    IntegrityPublicationComplete,
    IntegrityPublicationOutcome,
    IntegrityStageCleanupRequired,
    IntegrityStageRetained,
)
from .safe_output_models import SafeWriteStatus
from .safe_output_publication_identity import (
    FileIdentity,
    object_identity,
    regular_identity,
)


def replace_and_archive_integrity_report(
    parent_descriptor: int,
    staged_name: str,
    staged_identity: FileIdentity,
    destination_name: str,
    destination: Path,
    previous: FileIdentity,
    history: BoundIntegrityHistoryStage,
    check_containment: Callable[[], str | None],
    failure_status: IntegrityFailureStatus,
    forbidden_identities: frozenset[FileIdentity],
) -> IntegrityPublicationOutcome:
    """Exchange the public report, then commit the displaced inode to history."""
    try:
        require_history_stage_current(history, forbidden_identities)
        staged_current = object_identity(parent_descriptor, staged_name)
        destination_current = object_identity(parent_descriptor, destination_name)
    except OSError as exc:
        return IntegrityStageCleanupRequired(
            integrity_publication_failure(
                destination,
                integrity_publication_status(exc, failure_status),
                str(exc),
            )
        )
    if staged_current != staged_identity or destination_current != previous:
        return IntegrityStageCleanupRequired(
            integrity_publication_failure(
                destination,
                SafeWriteStatus.UNSAFE,
                "publication identities changed before exchange",
            )
        )
    try:
        rename_exchange(
            parent_descriptor,
            staged_name,
            parent_descriptor,
            destination_name,
        )
    except OSError as exc:
        return IntegrityStageRetained(
            integrity_publication_failure(
                destination,
                integrity_publication_status(exc, failure_status),
                f"{exc}; exchange result unproved and automatic cleanup skipped",
            )
        )
    try:
        published = regular_identity(parent_descriptor, destination_name)
        displaced = object_identity(parent_descriptor, staged_name)
        if published != staged_identity or displaced != previous:
            return IntegrityStageRetained(
                integrity_publication_failure(
                    destination,
                    SafeWriteStatus.UNSAFE,
                    "publication identities changed; automatic cleanup skipped",
                )
            )
        containment_error = check_containment()
        if containment_error is not None:
            return IntegrityStageRetained(
                integrity_publication_failure(
                    destination,
                    SafeWriteStatus.UNSAFE,
                    f"{containment_error}; automatic cleanup skipped",
                )
            )
        try:
            rename_noreplace(
                parent_descriptor,
                staged_name,
                history.stage_descriptor,
                INTEGRITY_HISTORY_REPORT_NAME,
            )
        except OSError as exc:
            archived = object_identity(
                history.stage_descriptor,
                INTEGRITY_HISTORY_REPORT_NAME,
            )
            if archived != previous:
                return IntegrityStageRetained(
                    integrity_publication_failure(
                        destination,
                        integrity_publication_status(exc, failure_status),
                        f"{exc}; archive move failed and automatic cleanup was skipped",
                    )
                )
        archived = object_identity(
            history.stage_descriptor,
            INTEGRITY_HISTORY_REPORT_NAME,
        )
        if archived != previous:
            return IntegrityStageRetained(
                integrity_publication_failure(
                    destination,
                    SafeWriteStatus.UNSAFE,
                    "archived report identity changed; history stage left untouched",
                )
            )
        require_history_stage_current(history, forbidden_identities)
        proof = write_integrity_history_generation(history, destination_name, previous)
        sync_directory_descriptor(history.stage_descriptor)
        require_history_stage_current(history, forbidden_identities)
        rename_noreplace(
            history.bucket_descriptor,
            history.stage_name,
            history.bucket_descriptor,
            history.generation_id,
        )
        require_history_generation_current(history, forbidden_identities)
        require_integrity_history_generation(history, proof)
        sync_directory_descriptor(history.bucket_descriptor)
        sync_directory_descriptor(parent_descriptor)
        require_history_generation_current(history, forbidden_identities)
        require_integrity_history_generation(history, proof)
        if regular_identity(parent_descriptor, destination_name) != staged_identity:
            return IntegrityStageRetained(
                integrity_publication_failure(
                    destination,
                    SafeWriteStatus.UNSAFE,
                    "published report identity changed after history commit",
                )
            )
        containment_error = check_containment()
        if containment_error is not None:
            return IntegrityStageRetained(
                integrity_publication_failure(
                    destination,
                    SafeWriteStatus.UNSAFE,
                    containment_error,
                )
            )
    except OSError as exc:
        return IntegrityStageRetained(
            integrity_publication_failure(
                destination,
                integrity_publication_status(exc, failure_status),
                f"{exc}; automatic cleanup skipped",
            )
        )
    return IntegrityPublicationComplete(None)


__all__ = ("replace_and_archive_integrity_report",)
