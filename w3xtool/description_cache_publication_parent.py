"""Bind publication validation and retention to one held parent directory."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .description_cache_publication_errors import (
    DescriptionCachePublicationError,
    PublicationCommitContextError,
    installed_context_error,
    merge_failures,
)
from .description_cache_publication_evidence import finalize_error_evidence
from .description_cache_publication_fs import DirectoryIdentity
from .description_cache_publication_models import (
    RetainedCacheRecord,
    RetainedCacheRole,
)
from .description_cache_publication_parent_identity import require_parent_identity
from .trusted_description_cache_models import VerifiedDescriptionCache


type ValidateAt = Callable[[int, Path], VerifiedDescriptionCache]
type RawRetain = Callable[
    [int, Path, DirectoryIdentity, RetainedCacheRole],
    RetainedCacheRecord,
]
type BoundRetain = Callable[
    [Path, DirectoryIdentity, RetainedCacheRole],
    RetainedCacheRecord,
]


@dataclass(frozen=True, slots=True)
class ParentBoundValidator:
    """Validate and retain only below one continuously proven parent."""

    parent_descriptor: int
    parent: Path
    parent_identity: DirectoryIdentity
    validator: ValidateAt
    retainer: RawRetain

    def require_current_parent(self) -> None:
        """Require the public parent name to remain bound to the held directory."""
        require_parent_identity(
            self.parent_descriptor,
            self.parent,
            self.parent_identity,
        )

    def require_valid(self, path: Path) -> VerifiedDescriptionCache:
        """Validate one cache only while its parent remains exactly bound."""
        if path.parent != self.parent:
            raise PublicationCommitContextError(
                "cache validation escaped the held publication parent; NEEDS_CONTEXT"
            )
        self.require_current_parent()
        try:
            verified = self.validator(self.parent_descriptor, path)
        except OSError as validation_error:
            try:
                self.require_current_parent()
            except PublicationCommitContextError as parent_error:
                parent_error.replace_failures(
                    merge_failures(
                        (validation_error,),
                        parent_error.failures,
                    )
                )
                raise
            raise
        self.require_current_parent()
        return verified

    def retain(
        self,
        path: Path,
        expected: DirectoryIdentity,
        role: RetainedCacheRole,
    ) -> RetainedCacheRecord:
        """Retain one object while its public parent remains bound."""
        if path.parent != self.parent:
            raise PublicationCommitContextError(
                "retention escaped the held publication parent; NEEDS_CONTEXT"
            )
        self.require_current_parent()
        retained = self.retainer(
            self.parent_descriptor,
            path,
            expected,
            role,
        )
        try:
            self.require_current_parent()
        except DescriptionCachePublicationError as context_error:
            finalized = finalize_error_evidence(
                self.parent_descriptor,
                self.parent,
                self.parent_identity,
                context_error,
                earlier_retained=(retained,),
            )
            raise installed_context_error(retained, finalized)
        return retained


__all__ = ("BoundRetain", "ParentBoundValidator")
