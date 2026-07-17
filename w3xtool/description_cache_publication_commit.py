"""Retain the previous generation at the replacement commit point."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .description_cache_publication_errors import (
    DescriptionCachePublicationError,
    PublicationCommitContextError,
    RetainedObjectInstalledContextError,
    merge_failures,
    merge_retained,
)
from .description_cache_publication_fs import DirectoryIdentity
from .description_cache_publication_models import (
    DescriptionCachePublicationProof,
    DescriptionCachePublicationResult,
    RetainedCacheExpectation,
    RetainedCacheRecord,
    RetainedCacheRole,
)
from .description_cache_publication_named_leaf import (
    reprove_retained,
    reprove_transient,
)
from .description_cache_publication_recovery import restore_previous_generation
from .description_cache_publication_retention_names import RetainedCacheNames
from .description_cache_publication_rollback_selection import (
    select_live_identity_path,
)
from .trusted_description_cache_models import VerifiedDescriptionCache


type Exchange = Callable[[int, str, str], None]
type Rename = Callable[[int, str, str], None]
type Sync = Callable[[int], None]
type Validate = Callable[[Path], VerifiedDescriptionCache]
type BoundRetain = Callable[
    [Path, DirectoryIdentity, RetainedCacheRole],
    RetainedCacheRecord,
]


def commit_replacement(
    parent_descriptor: int,
    parent_identity: DirectoryIdentity,
    output: Path,
    output_identity: DirectoryIdentity,
    backup: Path,
    backup_identity: DirectoryIdentity,
    stage: Path,
    names: RetainedCacheNames,
    verified: VerifiedDescriptionCache,
    previous_verified: VerifiedDescriptionCache,
    rename_exchange: Exchange,
    rename_noreplace: Rename,
    require_valid: Validate,
    retain: BoundRetain,
    sync_parent: Sync,
) -> DescriptionCachePublicationProof:
    """Retain the old generation or roll back without deleting either one."""
    try:
        retained = retain(
            backup,
            backup_identity,
            RetainedCacheRole.PREVIOUS,
        )
    except RetainedObjectInstalledContextError:
        raise
    except DescriptionCachePublicationError as retention_error:
        try:
            rollback_source = select_live_identity_path(
                parent_descriptor,
                output.parent,
                parent_identity,
                (
                    backup,
                    *(
                        record.path
                        for record in retention_error.retained
                        if record.identity == backup_identity
                    ),
                ),
                backup_identity,
                retention_error.retained,
                retention_error.transient,
            )
            recovered = restore_previous_generation(
                parent_descriptor,
                parent_identity,
                output,
                output_identity,
                rollback_source,
                backup_identity,
                stage,
                names,
                rename_exchange,
                rename_noreplace,
                require_valid,
                retain,
                sync_parent,
                retention_error.retained,
                retention_error.transient,
                f"previous-generation retention failed: {retention_error}",
            )
        except PublicationCommitContextError as restoration_error:
            restoration_error.replace_failures(
                merge_failures(
                    (*retention_error.failures, retention_error),
                    restoration_error.failures,
                )
            )
            raise
        rollback_proof = reprove_retained(
            parent_descriptor,
            output.parent,
            parent_identity,
            retention_error.retained,
        )
        retention_error.replace_retained(
            merge_retained(
                rollback_proof.retained,
                (recovered,),
            )
        )
        rollback_transient = reprove_transient(
            parent_descriptor,
            output.parent,
            parent_identity,
            (*retention_error.transient, *rollback_proof.transient),
        )
        retention_error.replace_transient(rollback_transient.transient)
        retention_error.replace_failures(
            merge_failures(
                retention_error.failures,
                (*rollback_proof.failures, *rollback_transient.failures),
            )
        )
        raise

    live_proof = reprove_retained(
        parent_descriptor,
        output.parent,
        parent_identity,
        (retained,),
    )
    if (
        live_proof.retained != (retained,)
        or live_proof.transient
        or live_proof.failures
    ):
        raise PublicationCommitContextError(
            "retained previous generation cannot be re-proved; NEEDS_CONTEXT",
            live_proof.retained,
            live_proof.transient,
            live_proof.failures,
        )
    live = live_proof.retained
    expectation = RetainedCacheExpectation(live[0], previous_verified)
    return DescriptionCachePublicationProof(
        DescriptionCachePublicationResult(verified, live),
        (expectation,),
    )


__all__ = ("commit_replacement",)
