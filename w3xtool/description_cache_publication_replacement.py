"""Atomic exchange and validation of one existing trusted cache."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .description_cache_publication_commit import commit_replacement
from .description_cache_publication_errors import (
    DescriptionCacheConcurrentDestinationError,
    DescriptionCachePublicationError,
    PublicationCommitContextError,
    merge_failures,
)
from .description_cache_publication_fs import DirectoryIdentity
from .description_cache_publication_models import (
    DescriptionCachePublicationProof,
    RetainedCacheRecord,
    RetainedCacheRole,
)
from .description_cache_publication_replacement_restore import (
    require_replacement_identity,
)
from .description_cache_publication_rollback_handoff import (
    ReplacementRollback,
)
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


def publish_replacement(
    parent_descriptor: int,
    parent_identity: DirectoryIdentity,
    stage: Path,
    stage_identity: DirectoryIdentity,
    stage_verified: VerifiedDescriptionCache,
    output: Path,
    output_identity: DirectoryIdentity,
    previous_verified: VerifiedDescriptionCache,
    backup: Path,
    names: RetainedCacheNames,
    rename_exchange: Exchange,
    rename_noreplace: Rename,
    require_valid: Validate,
    retain: BoundRetain,
    sync_parent: Sync,
) -> DescriptionCachePublicationProof:
    """Exchange two exact generations and retain the previous one."""
    rollback = ReplacementRollback(
        parent_descriptor,
        parent_identity,
        output,
        stage_identity,
        stage,
        names,
        rename_exchange,
        rename_noreplace,
        retain,
        sync_parent,
    )
    try:
        rename_exchange(parent_descriptor, stage.name, output.name)
    except OSError as cause:
        recovered = rollback.restore(
            cause,
            stage,
            output_identity,
            require_valid,
            str(cause),
        )
        raise DescriptionCachePublicationError(
            str(cause), (recovered,), failures=(cause,)
        ) from cause
    try:
        require_replacement_identity(parent_descriptor, output.name, stage_identity)
    except OSError as cause:
        recovered = rollback.restore(
            cause,
            stage,
            output_identity,
            require_valid,
            str(cause),
        )
        raise DescriptionCachePublicationError(
            str(cause), (recovered,), failures=(cause,)
        ) from cause
    try:
        require_replacement_identity(parent_descriptor, stage.name, output_identity)
    except OSError as cause:
        displaced_identity = rollback.read_identity(stage.name, cause)
        rollback_failure = cause

        def validate_displaced(path: Path) -> VerifiedDescriptionCache:
            if (
                rollback.read_identity(path.name, rollback_failure)
                == displaced_identity
            ):
                return stage_verified
            return require_valid(path)

        recovered = rollback.restore(
            rollback_failure,
            stage,
            displaced_identity,
            validate_displaced,
            "destination changed immediately before atomic exchange",
        )
        raise DescriptionCacheConcurrentDestinationError(
            "destination changed immediately before atomic exchange",
            (recovered,),
            failures=(cause,),
        ) from cause
    try:
        sync_parent(parent_descriptor)
        verified = require_valid(output)
        if verified != stage_verified:
            raise DescriptionCachePublicationError(
                "published replacement differs from the descriptor-verified stage"
            )
        require_replacement_identity(parent_descriptor, output.name, stage_identity)
        displaced = require_valid(stage)
        if displaced != previous_verified:
            raise DescriptionCachePublicationError(
                "displaced generation differs from the pre-exchange output"
            )
        require_replacement_identity(parent_descriptor, stage.name, output_identity)
    except OSError as cause:
        recovered = rollback.restore(
            cause,
            stage,
            output_identity,
            require_valid,
            str(cause),
        )
        raise DescriptionCachePublicationError(
            str(cause), (recovered,), failures=(cause,)
        ) from cause

    try:
        rename_noreplace(parent_descriptor, stage.name, backup.name)
    except OSError as cause:
        try:
            recovery = select_live_identity_path(
                parent_descriptor,
                output.parent,
                parent_identity,
                (stage, backup),
                output_identity,
                (),
                (),
            )
        except PublicationCommitContextError as selection_error:
            selection_error.replace_failures(
                merge_failures((cause,), selection_error.failures)
            )
            raise selection_error from cause
        recovered = rollback.restore(
            cause,
            recovery,
            output_identity,
            require_valid,
            str(cause),
        )
        raise DescriptionCachePublicationError(
            str(cause), (recovered,), failures=(cause,)
        ) from cause
    try:
        sync_parent(parent_descriptor)
        displaced = require_valid(backup)
        if displaced != previous_verified:
            raise DescriptionCachePublicationError(
                "backup generation differs from the pre-exchange output"
            )
        require_replacement_identity(parent_descriptor, backup.name, output_identity)
        require_replacement_identity(parent_descriptor, output.name, stage_identity)
    except OSError as cause:
        recovered = rollback.restore(
            cause,
            backup,
            output_identity,
            require_valid,
            str(cause),
        )
        raise DescriptionCachePublicationError(
            str(cause), (recovered,), failures=(cause,)
        ) from cause
    return commit_replacement(
        parent_descriptor,
        parent_identity,
        output,
        stage_identity,
        backup,
        output_identity,
        stage,
        names,
        verified,
        previous_verified,
        rename_exchange,
        rename_noreplace,
        require_valid,
        retain,
        sync_parent,
    )


__all__ = ("publish_replacement",)
