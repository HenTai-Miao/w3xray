"""Descriptor-anchored transaction for one validated cache stage."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .description_cache_publication_absent import publish_absent
from .description_cache_publication_errors import (
    DescriptionCacheConcurrentDestinationError,
    DescriptionCachePublicationError,
    PublicationCommitContextError,
)
from .description_cache_publication_fs import (
    DirectoryIdentity,
    directory_identity,
)
from .description_cache_publication_models import (
    DescriptionCachePublicationProof,
    RetainedCacheRecord,
    RetainedCacheRole,
)
from .description_cache_publication_parent import ParentBoundValidator
from .description_cache_publication_parent_identity import (
    parent_descriptor_identity,
    require_parent_identity,
)
from .description_cache_publication_replacement import publish_replacement
from .description_cache_publication_retention_durability import retain_durably
from .description_cache_publication_retention_names import RetainedCacheNames
from .description_cache_publication_stage_identity import descriptor_identity
from .trusted_description_cache import (
    load_trusted_description_cache_from_descriptor,
)
from .trusted_description_cache_models import (
    VerifiedDescriptionCache,
    VerifiedDescriptionCacheGeneration,
)


type Rename = Callable[[int, str, str], None]
type Exchange = Callable[[int, str, str], None]
type ValidateAt = Callable[[int, Path], VerifiedDescriptionCache]
type Sync = Callable[[int], None]


def publish_valid_stage(
    parent_descriptor: int,
    stage_descriptor: int,
    stage: Path,
    stage_identity: DirectoryIdentity,
    stage_generation: VerifiedDescriptionCacheGeneration,
    output: Path,
    backup: Path,
    names: RetainedCacheNames,
    parent_identity: DirectoryIdentity,
    rename_noreplace: Rename,
    rename_exchange: Exchange,
    require_valid_at: ValidateAt,
    sync_parent: Sync,
) -> DescriptionCachePublicationProof:
    """Publish a held and completely re-read stage without reopening it."""
    if stage.parent != output.parent or backup.parent != output.parent:
        raise DescriptionCachePublicationError("publication paths have mixed parents")
    if parent_descriptor_identity(parent_descriptor) != parent_identity:
        raise PublicationCommitContextError(
            "publication parent descriptor identity changed; NEEDS_CONTEXT"
        )
    require_parent_identity(parent_descriptor, output.parent, parent_identity)

    def raw_retain(
        descriptor: int,
        path: Path,
        expected: DirectoryIdentity,
        role: RetainedCacheRole,
    ) -> RetainedCacheRecord:
        return retain_durably(
            descriptor,
            output.parent,
            parent_identity,
            path,
            expected,
            names,
            role,
            rename_noreplace,
            sync_parent,
        )

    binding = ParentBoundValidator(
        parent_descriptor,
        output.parent,
        parent_identity,
        require_valid_at,
        raw_retain,
    )
    binding.require_current_parent()
    try:
        output_identity = directory_identity(parent_descriptor, output.name)
    except FileNotFoundError:
        _require_exact_stage(
            parent_descriptor,
            stage_descriptor,
            stage,
            stage_identity,
            stage_generation,
            parent_identity,
        )
        return publish_absent(
            parent_descriptor,
            parent_identity,
            stage,
            output,
            stage_identity,
            stage_generation.verified,
            rename_noreplace,
            binding.require_valid,
            binding.retain,
            sync_parent,
        )
    previous_verified = binding.require_valid(output)
    _require_identity(parent_descriptor, output.name, output_identity)
    _require_exact_stage(
        parent_descriptor,
        stage_descriptor,
        stage,
        stage_identity,
        stage_generation,
        parent_identity,
    )
    return publish_replacement(
        parent_descriptor,
        parent_identity,
        stage,
        stage_identity,
        stage_generation.verified,
        output,
        output_identity,
        previous_verified,
        backup,
        names,
        rename_exchange,
        rename_noreplace,
        binding.require_valid,
        binding.retain,
        sync_parent,
    )


def _require_exact_stage(
    parent_descriptor: int,
    stage_descriptor: int,
    stage: Path,
    stage_identity: DirectoryIdentity,
    stage_generation: VerifiedDescriptionCacheGeneration,
    parent_identity: DirectoryIdentity,
) -> None:
    require_parent_identity(parent_descriptor, stage.parent, parent_identity)
    if descriptor_identity(stage_descriptor) != stage_identity:
        raise PublicationCommitContextError(
            "held stage descriptor identity changed; NEEDS_CONTEXT"
        )
    _require_identity(parent_descriptor, stage.name, stage_identity)
    reread = load_trusted_description_cache_from_descriptor(
        stage_descriptor,
        stage,
        stage_generation.proof.leaves,
    )
    if reread != stage_generation:
        raise DescriptionCachePublicationError(
            "held stage generation changed before publication"
        )


def _require_identity(
    parent_descriptor: int,
    name: str,
    expected: DirectoryIdentity,
) -> None:
    if directory_identity(parent_descriptor, name) != expected:
        raise DescriptionCacheConcurrentDestinationError(
            "existing cache changed identity during validation"
        )


__all__ = (
    "DescriptionCacheConcurrentDestinationError",
    "DescriptionCachePublicationError",
    "publish_valid_stage",
)
