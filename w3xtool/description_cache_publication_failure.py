"""Final evidence assembly for a failed publication transaction."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Never, assert_never

from .description_cache_publication_errors import (
    DescriptionCachePublicationError,
    PublicationCommitContextError,
    merge_failures,
    merge_retained,
)
from .description_cache_publication_evidence import finalize_error_evidence
from .description_cache_publication_models import RetainedCacheRecord
from .description_cache_publication_named_leaf import capture_named_transient
from .description_cache_publication_retention_names import RetainedCacheNames
from .description_cache_publication_stage import BoundDescriptionCacheStage
from .description_cache_publication_stage_finalization import (
    finalize_private_artifacts,
)


type Rename = Callable[[int, str, str], None]
type Sync = Callable[[int], None]


def _raise_after_private_finalization(
    bound: BoundDescriptionCacheStage,
    backup: Path,
    names: RetainedCacheNames,
    output: Path,
    published_records: tuple[RetainedCacheRecord, ...],
    cause: Exception,
    rename_noreplace: Rename,
    sync_parent: Sync,
) -> Never:
    """Normalize both private leaves before surfacing one typed failure."""
    match cause:
        case DescriptionCachePublicationError() as typed_error:
            publication_error = typed_error
        case Exception() as ordinary_error:
            publication_error = DescriptionCachePublicationError(
                str(ordinary_error),
                failures=(ordinary_error,),
            )
        case unreachable:
            assert_never(unreachable)
    known_records = merge_retained(
        published_records,
        publication_error.retained,
    )
    try:
        private_records = finalize_private_artifacts(
            bound,
            backup,
            output,
            names,
            rename_noreplace,
            sync_parent,
            known_records,
            publication_error.transient,
        )
    except Exception as finalization_cause:  # noqa: BROAD_EXCEPT_OK - finalizer evidence
        match finalization_cause:
            case DescriptionCachePublicationError() as typed_error:
                finalization_error = typed_error
            case Exception() as ordinary_error:
                finalization_error = PublicationCommitContextError(
                    f"private finalization raised an ordinary exception: "
                    f"{ordinary_error}; NEEDS_CONTEXT",
                    failures=(ordinary_error,),
                )
            case unreachable:
                assert_never(unreachable)
        finalization_error.replace_failures(
            merge_failures(
                (*publication_error.failures, publication_error),
                finalization_error.failures,
            )
        )
        finalized = finalize_error_evidence(
            bound.parent_descriptor,
            bound.stage.parent,
            bound.parent_identity,
            finalization_error,
            earlier_retained=known_records,
            earlier_transient=publication_error.transient,
            parent_loss_evidence=capture_named_transient(
                bound.parent_descriptor,
                bound.stage.parent,
                bound.parent_identity,
                output,
            ),
        )
        _raise_finalized(finalized, finalization_cause)
    finalized = finalize_error_evidence(
        bound.parent_descriptor,
        bound.stage.parent,
        bound.parent_identity,
        publication_error,
        earlier_retained=published_records,
        later_retained=private_records,
        parent_loss_evidence=capture_named_transient(
            bound.parent_descriptor,
            bound.stage.parent,
            bound.parent_identity,
            output,
        ),
    )
    _raise_finalized(finalized, cause)


def _raise_finalized(
    error: DescriptionCachePublicationError,
    cause: Exception,
) -> Never:
    """Raise one typed boundary without replacing an existing cause."""
    if error is not cause:
        error.replace_failures(merge_failures(error.failures, (cause,)))
    raise error


__all__ = ()
