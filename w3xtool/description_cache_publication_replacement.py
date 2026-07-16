"""Atomic exchange and validation of one existing trusted cache."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .description_cache_publication_commit import commit_replacement
from .description_cache_publication_errors import (
    DescriptionCacheConcurrentDestinationError,
    PublicationCommitContextError,
)
from .description_cache_publication_fs import (
    DirectoryIdentity,
    directory_identity,
    object_identity,
)
from .description_cache_publication_recovery import restore_previous_generation
from .trusted_description_cache import VerifiedDescriptionCache


type Exchange = Callable[[int, str, str], None]
type Remove = Callable[[int, str, DirectoryIdentity], None]
type Rename = Callable[[int, str, str], None]
type Sync = Callable[[int], None]
type Validate = Callable[[Path], VerifiedDescriptionCache]


def publish_replacement(
    parent_descriptor: int,
    stage: Path,
    stage_identity: DirectoryIdentity,
    output: Path,
    output_identity: DirectoryIdentity,
    backup: Path,
    rename_exchange: Exchange,
    rename_noreplace: Rename,
    require_valid: Validate,
    remove_directory: Remove,
    sync_parent: Sync,
) -> VerifiedDescriptionCache:
    """Exchange a proven stage with a proven existing generation."""
    rename_exchange(parent_descriptor, stage.name, output.name)
    try:
        _require_identity(parent_descriptor, output.name, stage_identity)
    except OSError as exc:
        _restore(
            parent_descriptor,
            output,
            stage_identity,
            stage,
            output_identity,
            stage,
            rename_exchange,
            rename_noreplace,
            require_valid,
            remove_directory,
            sync_parent,
            str(exc),
        )
        raise
    try:
        _require_identity(parent_descriptor, stage.name, output_identity)
    except OSError as exc:
        _restore_displaced_destination(
            parent_descriptor,
            output,
            stage,
            stage_identity,
            rename_exchange,
            require_valid,
            sync_parent,
        )
        raise DescriptionCacheConcurrentDestinationError(
            "destination changed immediately before atomic exchange"
        ) from exc
    try:
        sync_parent(parent_descriptor)
        verified = require_valid(output)
        _require_identity(parent_descriptor, output.name, stage_identity)
        _ = require_valid(stage)
        _require_identity(parent_descriptor, stage.name, output_identity)
    except OSError as exc:
        _restore(
            parent_descriptor,
            output,
            stage_identity,
            stage,
            output_identity,
            stage,
            rename_exchange,
            rename_noreplace,
            require_valid,
            remove_directory,
            sync_parent,
            str(exc),
        )
        raise

    try:
        rename_noreplace(parent_descriptor, stage.name, backup.name)
    except OSError as exc:
        _restore(
            parent_descriptor,
            output,
            stage_identity,
            stage,
            output_identity,
            stage,
            rename_exchange,
            rename_noreplace,
            require_valid,
            remove_directory,
            sync_parent,
            str(exc),
        )
        raise
    try:
        sync_parent(parent_descriptor)
        _ = require_valid(backup)
        _require_identity(parent_descriptor, backup.name, output_identity)
        _require_identity(parent_descriptor, output.name, stage_identity)
    except OSError as exc:
        _restore(
            parent_descriptor,
            output,
            stage_identity,
            backup,
            output_identity,
            stage,
            rename_exchange,
            rename_noreplace,
            require_valid,
            remove_directory,
            sync_parent,
            str(exc),
        )
        raise
    return commit_replacement(
        parent_descriptor,
        output,
        stage_identity,
        backup,
        output_identity,
        stage,
        verified,
        remove_directory,
        rename_exchange,
        rename_noreplace,
        require_valid,
        sync_parent,
    )


def _restore(
    parent_descriptor: int,
    output: Path,
    staged_identity: DirectoryIdentity,
    recovery: Path,
    previous_identity: DirectoryIdentity,
    stage: Path,
    rename_exchange: Exchange,
    rename_noreplace: Rename,
    require_valid: Validate,
    remove_directory: Remove,
    sync_parent: Sync,
    detail: str,
) -> None:
    restore_previous_generation(
        parent_descriptor,
        output,
        staged_identity,
        recovery,
        previous_identity,
        stage,
        rename_exchange,
        rename_noreplace,
        require_valid,
        remove_directory,
        sync_parent,
        detail,
    )


def _require_identity(
    parent_descriptor: int,
    name: str,
    expected: DirectoryIdentity,
) -> None:
    if directory_identity(parent_descriptor, name) != expected:
        raise DescriptionCacheConcurrentDestinationError(
            "publication object changed identity"
        )


def _restore_displaced_destination(
    parent_descriptor: int,
    output: Path,
    stage: Path,
    staged_identity: DirectoryIdentity,
    rename_exchange: Exchange,
    require_valid: Validate,
    sync_parent: Sync,
) -> None:
    """Reverse one exchange that displaced an unexpected destination object."""
    try:
        displaced_identity = object_identity(parent_descriptor, stage.name)
        if object_identity(parent_descriptor, output.name) != staged_identity:
            raise PublicationCommitContextError(
                "publication output changed before reverse exchange; NEEDS_CONTEXT"
            )
        rename_exchange(parent_descriptor, output.name, stage.name)
        if object_identity(parent_descriptor, output.name) != displaced_identity:
            raise PublicationCommitContextError(
                "displaced destination changed during recovery; NEEDS_CONTEXT"
            )
        _require_identity(parent_descriptor, stage.name, staged_identity)
        sync_parent(parent_descriptor)
        _ = require_valid(stage)
        _require_identity(parent_descriptor, stage.name, staged_identity)
    except PublicationCommitContextError:
        raise
    except OSError as exc:
        raise PublicationCommitContextError(
            "cannot restore displaced destination; NEEDS_CONTEXT"
        ) from exc


__all__ = ("publish_replacement",)
