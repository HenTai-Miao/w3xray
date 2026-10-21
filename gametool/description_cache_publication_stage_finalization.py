"""Independent normalization of transaction-private publication leaves."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import assert_never

from .description_cache_publication_backup_finalization import retain_backup
from .description_cache_publication_errors import (
    DescriptionCachePublicationError,
    PublicationCommitContextError,
    merge_failures,
    merge_retained,
)
from .description_cache_publication_evidence import (
    finalize_error_evidence,
    require_live_retained_evidence,
)
from .description_cache_publication_models import (
    PublicationTransientRecord,
    RetainedCacheRecord,
)
from .description_cache_publication_private_attempt import (
    attempt_private,
    record_tuple,
)
from .description_cache_publication_retention_names import RetainedCacheNames
from .description_cache_publication_stage import BoundDescriptionCacheStage
from .description_cache_publication_stage_retention import retain_stage


type Rename = Callable[[int, str, str], None]
type Sync = Callable[[int], None]


def finalize_private_artifacts(
    bound: BoundDescriptionCacheStage,
    backup: Path,
    output: Path,
    names: RetainedCacheNames,
    rename_noreplace: Rename,
    sync_parent: Sync,
    known_retained: tuple[RetainedCacheRecord, ...] = (),
    known_transient: tuple[PublicationTransientRecord, ...] = (),
) -> tuple[RetainedCacheRecord, ...]:
    """Attempt both private leaves and return only live normalized records."""
    backup_attempt = attempt_private(
        bound,
        backup,
        None,
        lambda: retain_backup(
            bound,
            backup,
            names,
            rename_noreplace,
            sync_parent,
        ),
    )
    stage_known_retained = merge_retained(
        known_retained,
        record_tuple(backup_attempt.record),
    )
    stage_known_transient = known_transient
    match backup_attempt.error:
        case None:
            pass
        case DescriptionCachePublicationError() as backup_error:
            stage_known_retained = merge_retained(
                stage_known_retained,
                backup_error.retained,
            )
            stage_known_transient = tuple(
                dict.fromkeys((*stage_known_transient, *backup_error.transient))
            )
        case unreachable:
            assert_never(unreachable)
    stage_attempt = attempt_private(
        bound,
        bound.stage,
        bound.stage_identity,
        lambda: retain_stage(
            bound,
            output,
            names,
            rename_noreplace,
            sync_parent,
            stage_known_retained,
            stage_known_transient,
        ),
    )
    records = merge_retained(
        record_tuple(backup_attempt.record),
        record_tuple(stage_attempt.record),
    )
    errors = tuple(
        error
        for error in (backup_attempt.error, stage_attempt.error)
        if error is not None
    )
    if errors:
        retained = merge_retained(known_retained, records)
        transient = known_transient
        failures: tuple[Exception, ...] = ()
        for error in errors:
            retained = merge_retained(retained, error.retained)
            transient = tuple(dict.fromkeys((*transient, *error.transient)))
            failures = merge_failures(failures, (*error.failures, error))
        context_error = PublicationCommitContextError(
            "one or more private artifacts could not be normalized; NEEDS_CONTEXT",
            retained,
            transient,
            failures,
        )
        raise finalize_error_evidence(
            bound.parent_descriptor,
            bound.stage.parent,
            bound.parent_identity,
            context_error,
        )
    return require_live_retained_evidence(
        bound.parent_descriptor,
        bound.stage.parent,
        bound.parent_identity,
        records,
    )


__all__ = ("finalize_private_artifacts", "retain_stage")
