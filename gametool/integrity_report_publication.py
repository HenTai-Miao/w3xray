"""Non-destructive publication for current and historical integrity reports."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .integrity_report_history_directory import prepare_integrity_history_stage
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
from .integrity_report_replacement import replace_and_archive_integrity_report
from .safe_output_models import SafeWriteStatus
from .safe_output_publication import publish_staged_file
from .safe_output_publication_identity import FileIdentity, regular_identity


type _ContainmentCheck = Callable[[], str | None]


def publish_integrity_report(
    parent_descriptor: int,
    staged_name: str,
    staged_identity: FileIdentity,
    destination_name: str,
    destination: Path,
    check_containment: _ContainmentCheck,
    failure_status: IntegrityFailureStatus,
    forbidden_identities: frozenset[FileIdentity],
) -> IntegrityPublicationOutcome:
    """Publish current content while moving an existing report into history."""
    try:
        previous = regular_identity(parent_descriptor, destination_name)
    except OSError as exc:
        return IntegrityStageCleanupRequired(
            integrity_publication_failure(
                destination,
                integrity_publication_status(exc, failure_status),
                str(exc),
            )
        )
    if previous is None:
        return IntegrityPublicationComplete(
            publish_staged_file(
                parent_descriptor,
                staged_name,
                staged_identity,
                destination_name,
                str(destination),
                check_containment,
                failure_status,
            )
        )
    containment_error = check_containment()
    if containment_error is not None:
        return IntegrityStageCleanupRequired(
            integrity_publication_failure(
                destination,
                SafeWriteStatus.UNSAFE,
                containment_error,
            )
        )
    try:
        history = prepare_integrity_history_stage(
            parent_descriptor,
            destination,
            forbidden_identities,
        )
    except OSError as exc:
        return IntegrityStageCleanupRequired(
            integrity_publication_failure(
                destination,
                integrity_publication_status(exc, failure_status),
                str(exc),
            )
        )
    try:
        with history:
            return replace_and_archive_integrity_report(
                parent_descriptor,
                staged_name,
                staged_identity,
                destination_name,
                destination,
                previous,
                history,
                check_containment,
                failure_status,
                forbidden_identities,
            )
    except OSError as exc:
        return IntegrityStageRetained(
            integrity_publication_failure(
                destination,
                integrity_publication_status(exc, failure_status),
                str(exc),
            )
        )


__all__ = ("publish_integrity_report",)
