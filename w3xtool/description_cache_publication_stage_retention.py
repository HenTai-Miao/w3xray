"""Final retention or location proof for the exact held stage."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .description_cache_publication_errors import (
    DescriptionCachePublicationError,
    PublicationCommitContextError,
    merge_failures,
    merge_retained,
)
from .description_cache_publication_models import (
    PublicationTransientRecord,
    RetainedCacheRecord,
    RetainedCacheRole,
    RetainedEvidenceReproof,
)
from .description_cache_publication_named_leaf import (
    read_named_leaf,
)
from .description_cache_publication_parent_identity import require_parent_identity
from .description_cache_publication_retention_durability import retain_durably
from .description_cache_publication_retention_names import RetainedCacheNames
from .description_cache_publication_stage import BoundDescriptionCacheStage
from .description_cache_publication_stage_location import locate_consumed_stage
from .description_cache_publication_stage_normalization import (
    capture_transient_record,
)


type Rename = Callable[[int, str, str], None]
type Sync = Callable[[int], None]


def retain_stage(
    bound: BoundDescriptionCacheStage,
    output: Path,
    names: RetainedCacheNames,
    rename_noreplace: Rename,
    sync_parent: Sync,
    known_retained: tuple[RetainedCacheRecord, ...],
    known_transient: tuple[PublicationTransientRecord, ...],
) -> RetainedCacheRecord | None:
    """Retain or locate the exact held stage without guessing by pathname."""
    if any(record.identity == bound.stage_identity for record in known_retained):
        return locate_consumed_stage(
            bound,
            output,
            names,
            known_retained=known_retained,
            known_transient=known_transient,
        )
    try:
        require_parent_identity(
            bound.parent_descriptor,
            bound.stage.parent,
            bound.parent_identity,
        )
    except PublicationCommitContextError as context_error:
        bound_evidence = _bound_evidence(bound)
        return locate_consumed_stage(
            bound,
            output,
            names,
            known_retained=merge_retained(
                known_retained,
                context_error.retained,
            ),
            known_transient=(
                *known_transient,
                *context_error.transient,
                *bound_evidence.transient,
            ),
            prior_failures=merge_failures(
                (*context_error.failures, context_error),
                bound_evidence.failures,
            ),
            detail="publication parent changed during final stage proof",
        )
    stage_proof = read_named_leaf(bound.parent_descriptor, bound.stage.name)
    if stage_proof.readable and stage_proof.identity is None:
        return locate_consumed_stage(
            bound,
            output,
            names,
            known_retained=known_retained,
            known_transient=known_transient,
        )
    if stage_proof.identity is None:
        bound_evidence = _bound_evidence(bound)
        return locate_consumed_stage(
            bound,
            output,
            names,
            known_retained=known_retained,
            known_transient=(
                *known_transient,
                *bound_evidence.transient,
            ),
            prior_failures=merge_failures(
                stage_proof.failures,
                bound_evidence.failures,
            ),
            detail="cannot prove final stage retention",
        )
    identity = stage_proof.identity
    if identity != bound.stage_identity:
        try:
            recovery = retain_durably(
                bound.parent_descriptor,
                bound.stage.parent,
                bound.parent_identity,
                bound.stage,
                identity,
                names,
                RetainedCacheRole.RECOVERY,
                rename_noreplace,
                sync_parent,
            )
        except DescriptionCachePublicationError as retention_error:
            return locate_consumed_stage(
                bound,
                output,
                names,
                known_retained=known_retained,
                known_transient=known_transient,
                later_retained=retention_error.retained,
                later_transient=retention_error.transient,
                prior_failures=(*retention_error.failures, retention_error),
                detail="foreign final-stage retention failed",
            )
        return locate_consumed_stage(
            bound,
            output,
            names,
            known_retained=known_retained,
            known_transient=known_transient,
            later_retained=(recovery,),
            detail="final stage leaf no longer names the held stage",
        )
    try:
        return retain_durably(
            bound.parent_descriptor,
            bound.stage.parent,
            bound.parent_identity,
            bound.stage,
            bound.stage_identity,
            names,
            RetainedCacheRole.FAILED_STAGE,
            rename_noreplace,
            sync_parent,
        )
    except DescriptionCachePublicationError as retention_error:
        return locate_consumed_stage(
            bound,
            output,
            names,
            known_retained=known_retained,
            known_transient=known_transient,
            later_retained=retention_error.retained,
            later_transient=retention_error.transient,
            prior_failures=(*retention_error.failures, retention_error),
            detail="failed-stage retention did not complete cleanly",
        )


def _bound_evidence(
    bound: BoundDescriptionCacheStage,
) -> RetainedEvidenceReproof:
    return capture_transient_record(
        bound.parent_descriptor,
        bound.stage,
        bound.parent_identity,
        bound.stage_identity,
    )


__all__ = ("retain_stage",)
