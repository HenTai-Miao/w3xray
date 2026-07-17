"""Ordered failure handoff from replacement into rollback recovery."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import assert_never

from .description_cache_publication_errors import (
    DescriptionCachePublicationError,
    PublicationCommitContextError,
    merge_failures,
)
from .description_cache_publication_fs import DirectoryIdentity, object_identity
from .description_cache_publication_models import (
    RetainedCacheRecord,
    RetainedCacheRole,
)
from .description_cache_publication_replacement_restore import restore_replacement
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


@dataclass(frozen=True, slots=True)
class ReplacementRollback:
    """Common replacement state plus ordered recovery failure handoff."""

    parent_descriptor: int
    parent_identity: DirectoryIdentity
    output: Path
    staged_identity: DirectoryIdentity
    stage: Path
    names: RetainedCacheNames
    rename_exchange: Exchange
    rename_noreplace: Rename
    retain: BoundRetain
    sync_parent: Sync

    def restore(
        self,
        initiating_failure: OSError,
        recovery: Path,
        previous_identity: DirectoryIdentity,
        require_valid: Validate,
        detail: str,
    ) -> RetainedCacheRecord:
        """Restore while preserving initiating and recovery event order."""
        try:
            return restore_replacement(
                self.parent_descriptor,
                self.parent_identity,
                self.output,
                self.staged_identity,
                recovery,
                previous_identity,
                self.stage,
                self.names,
                self.rename_exchange,
                self.rename_noreplace,
                require_valid,
                self.retain,
                self.sync_parent,
                detail,
            )
        except DescriptionCachePublicationError as recovery_error:
            recovery_error.replace_failures(
                merge_failures(
                    _observed_failures(initiating_failure),
                    recovery_error.failures,
                )
            )
            raise

    def read_identity(
        self,
        name: str,
        initiating_failure: OSError,
    ) -> DirectoryIdentity:
        """Read a rollback identity or ledger both consecutive proof failures."""
        try:
            return object_identity(self.parent_descriptor, name)
        except OSError as read_failure:
            raise PublicationCommitContextError(
                "rollback identity proof failed; NEEDS_CONTEXT",
                failures=merge_failures(
                    _observed_failures(initiating_failure),
                    _observed_failures(read_failure),
                ),
            ) from read_failure


def _observed_failures(failure: OSError) -> tuple[Exception, ...]:
    match failure:
        case DescriptionCachePublicationError() as typed_failure:
            return merge_failures(typed_failure.failures, (typed_failure,))
        case OSError() as ordinary_failure:
            return (ordinary_failure,)
        case unreachable:
            assert_never(unreachable)


__all__ = ("ReplacementRollback",)
