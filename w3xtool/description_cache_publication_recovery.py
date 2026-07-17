"""Identity-proven restoration for an exchanged cache generation."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Never

from .description_cache_publication_errors import (
    DescriptionCachePublicationError,
    PublicationCommitContextError,
    merge_failures,
    merge_retained,
)
from .description_cache_publication_fs import DirectoryIdentity, directory_identity
from .description_cache_publication_models import (
    PublicationTransientRecord,
    RetainedCacheRecord,
    RetainedCacheRole,
)
from .description_cache_publication_named_leaf import reprove_transient
from .description_cache_publication_recovery_state import (
    normalize_recovery_failure,
)
from .description_cache_publication_retention_names import RetainedCacheNames
from .trusted_description_cache_models import VerifiedDescriptionCache


type Exchange = Callable[[int, str, str], None]
type Rename = Callable[[int, str, str], None]
type Sync = Callable[[int], None]
type Validate = Callable[[Path], VerifiedDescriptionCache]
type BoundRetain = Callable[
    [Path, DirectoryIdentity, RetainedCacheRole],
    RetainedCacheRecord,
]


def restore_previous_generation(
    parent_descriptor: int,
    parent_identity: DirectoryIdentity,
    output: Path,
    staged_identity: DirectoryIdentity,
    recovery: Path,
    previous_identity: DirectoryIdentity,
    stage: Path,
    names: RetainedCacheNames,
    rename_exchange: Exchange,
    rename_noreplace: Rename,
    require_valid: Validate,
    retain: BoundRetain,
    sync_parent: Sync,
    prior_records: tuple[RetainedCacheRecord, ...],
    prior_transient: tuple[PublicationTransientRecord, ...],
    detail: str,
) -> RetainedCacheRecord:
    """Restore the previous output and retain the exact failed stage."""
    private = recovery

    def _raise_normalized_recovery_error(
        caught: DescriptionCachePublicationError,
    ) -> Never:
        current_records = merge_retained(prior_records, caught.retained)
        current_evidence = reprove_transient(
            parent_descriptor,
            output.parent,
            parent_identity,
            (*prior_transient, *caught.transient),
        )
        try:
            live = normalize_recovery_failure(
                parent_descriptor,
                output.parent,
                parent_identity,
                (private, recovery, stage),
                staged_identity,
                current_records,
                current_evidence.transient,
                merge_failures(
                    (*caught.failures, caught),
                    current_evidence.failures,
                ),
                names,
                retain,
                sync_parent,
            )
        except DescriptionCachePublicationError as normalization_error:
            normalization_error.replace_failures(
                merge_failures(
                    (*caught.failures, caught),
                    normalization_error.failures,
                )
            )
            raise
        final_transient = reprove_transient(
            parent_descriptor,
            output.parent,
            parent_identity,
            current_evidence.transient,
        )
        raise PublicationCommitContextError(
            f"{detail}; NEEDS_CONTEXT",
            live,
            final_transient.transient,
            merge_failures(
                (*caught.failures, caught),
                (*current_evidence.failures, *final_transient.failures),
            ),
        ) from caught

    try:
        _require_valid_identity(
            parent_descriptor,
            recovery,
            previous_identity,
            require_valid,
        )
        _require_identity(parent_descriptor, output.name, staged_identity)
        rename_exchange(parent_descriptor, output.name, recovery.name)
        _require_identity(parent_descriptor, output.name, previous_identity)
        _require_identity(parent_descriptor, recovery.name, staged_identity)
        sync_parent(parent_descriptor)
        _require_valid_identity(
            parent_descriptor,
            output,
            previous_identity,
            require_valid,
        )
        _require_valid_identity(
            parent_descriptor,
            recovery,
            staged_identity,
            require_valid,
        )
        if recovery.name != stage.name:
            rename_noreplace(parent_descriptor, recovery.name, stage.name)
            private = stage
            _require_identity(parent_descriptor, private.name, staged_identity)
            sync_parent(parent_descriptor)
        _require_valid_identity(
            parent_descriptor,
            private,
            staged_identity,
            require_valid,
        )
        return retain(private, staged_identity, RetainedCacheRole.FAILED_STAGE)
    except DescriptionCachePublicationError as caught:
        _raise_normalized_recovery_error(caught)
    except Exception as caught:  # noqa: BROAD_EXCEPT_OK - recovery evidence boundary
        wrapped = DescriptionCachePublicationError(
            str(caught),
            failures=(caught,),
        )
        _raise_normalized_recovery_error(wrapped)


def _require_valid_identity(
    parent_descriptor: int,
    path: Path,
    expected: DirectoryIdentity,
    require_valid: Validate,
) -> None:
    _ = require_valid(path)
    _require_identity(parent_descriptor, path.name, expected)


def _require_identity(
    parent_descriptor: int,
    name: str,
    expected: DirectoryIdentity,
) -> None:
    if directory_identity(parent_descriptor, name) != expected:
        raise PublicationCommitContextError(
            "publication identity changed during recovery; NEEDS_CONTEXT"
        )


__all__ = ("restore_previous_generation",)
