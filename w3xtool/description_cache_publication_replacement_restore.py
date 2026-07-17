"""Focused rollback adapter for replacement publication."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .description_cache_publication_errors import (
    DescriptionCacheConcurrentDestinationError,
)
from .description_cache_publication_fs import DirectoryIdentity, directory_identity
from .description_cache_publication_models import (
    RetainedCacheRecord,
    RetainedCacheRole,
)
from .description_cache_publication_recovery import restore_previous_generation
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


def restore_replacement(
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
    detail: str,
) -> RetainedCacheRecord:
    """Restore one failed replacement through the shared recovery boundary."""
    return restore_previous_generation(
        parent_descriptor,
        parent_identity,
        output,
        staged_identity,
        recovery,
        previous_identity,
        stage,
        names,
        rename_exchange,
        rename_noreplace,
        require_valid,
        retain,
        sync_parent,
        (),
        (),
        detail,
    )


def require_replacement_identity(
    parent_descriptor: int,
    name: str,
    expected: DirectoryIdentity,
) -> None:
    """Require one replacement directory name to keep its exact inode."""
    if directory_identity(parent_descriptor, name) != expected:
        raise DescriptionCacheConcurrentDestinationError(
            "publication object changed identity"
        )


__all__ = ("require_replacement_identity", "restore_replacement")
