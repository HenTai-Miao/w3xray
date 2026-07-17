"""Final normalization of one transaction-private backup leaf."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .description_cache_publication_errors import PublicationCommitContextError
from .description_cache_publication_evidence import finalize_error_evidence
from .description_cache_publication_models import (
    PublicationTransientRecord,
    RetainedCacheRecord,
    RetainedCacheRole,
)
from .description_cache_publication_named_leaf import read_named_leaf
from .description_cache_publication_parent_identity import require_parent_identity
from .description_cache_publication_retention_durability import retain_durably
from .description_cache_publication_retention_names import RetainedCacheNames
from .description_cache_publication_stage import BoundDescriptionCacheStage


type Rename = Callable[[int, str, str], None]
type Sync = Callable[[int], None]


def retain_backup(
    bound: BoundDescriptionCacheStage,
    backup: Path,
    names: RetainedCacheNames,
    rename_noreplace: Rename,
    sync_parent: Sync,
) -> RetainedCacheRecord | None:
    """Retain one current backup object as recovery evidence."""
    require_parent_identity(
        bound.parent_descriptor,
        bound.stage.parent,
        bound.parent_identity,
    )
    proof = read_named_leaf(bound.parent_descriptor, backup.name)
    if proof.readable and proof.identity is None:
        return None
    if proof.identity is None:
        context_error = PublicationCommitContextError(
            "cannot prove final backup retention; NEEDS_CONTEXT",
            transient=(
                PublicationTransientRecord(
                    bound.stage.parent,
                    backup.name,
                    bound.parent_identity,
                    None,
                ),
            ),
            failures=proof.failures,
        )
        finalized = finalize_error_evidence(
            bound.parent_descriptor,
            bound.stage.parent,
            bound.parent_identity,
            context_error,
        )
        raise finalized
    identity = proof.identity
    return retain_durably(
        bound.parent_descriptor,
        bound.stage.parent,
        bound.parent_identity,
        backup,
        identity,
        names,
        RetainedCacheRole.RECOVERY,
        rename_noreplace,
        sync_parent,
    )


__all__ = ("retain_backup",)
