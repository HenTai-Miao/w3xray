"""Recoverable cleanup and explicit commit for cache replacement."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .description_cache_publication_errors import DescriptionCachePublicationError
from .description_cache_publication_fs import (
    DirectoryIdentity,
    directory_identity,
)
from .trusted_description_cache import VerifiedDescriptionCache


type _Remove = Callable[[int, str, DirectoryIdentity], None]
type _Rename = Callable[[int, str, str], None]
type _Sync = Callable[[int], None]
type _Validate = Callable[[Path], VerifiedDescriptionCache]


class PublicationCommitContextError(DescriptionCachePublicationError):
    """A post-publication state needs explicit recovery context."""

    __slots__: tuple[str, ...] = ()


def commit_replacement(
    parent_descriptor: int,
    output: Path,
    output_identity: DirectoryIdentity,
    backup: Path,
    backup_identity: DirectoryIdentity,
    verified: VerifiedDescriptionCache,
    remove_directory: _Remove,
    rename_noreplace: _Rename,
    require_valid: _Validate,
    sync_parent: _Sync,
) -> VerifiedDescriptionCache:
    """Rollback recoverable cleanup errors, then cross one commit point."""
    try:
        remove_directory(parent_descriptor, backup.name, backup_identity)
    except OSError as cleanup_error:
        _rollback_cleanup_failure(
            parent_descriptor,
            output,
            output_identity,
            backup,
            backup_identity,
            remove_directory,
            rename_noreplace,
            require_valid,
            sync_parent,
            cleanup_error,
        )
        raise

    # Commit point: the verified old generation no longer has a directory name.
    try:
        sync_parent(parent_descriptor)
    except OSError:
        _require_identity(parent_descriptor, output.name, output_identity)
        try:
            return require_valid(output)
        except OSError as validation_error:
            detail = (
                "committed output failed revalidation after final sync failure; "
                + "NEEDS_CONTEXT"
            )
            raise PublicationCommitContextError(detail) from validation_error
    return verified


def _rollback_cleanup_failure(
    parent_descriptor: int,
    output: Path,
    output_identity: DirectoryIdentity,
    backup: Path,
    backup_identity: DirectoryIdentity,
    remove_directory: _Remove,
    rename_noreplace: _Rename,
    require_valid: _Validate,
    sync_parent: _Sync,
    cleanup_error: OSError,
) -> None:
    try:
        _ = require_valid(backup)
        _require_identity(parent_descriptor, backup.name, backup_identity)
        remove_directory(parent_descriptor, output.name, output_identity)
        rename_noreplace(parent_descriptor, backup.name, output.name)
        sync_parent(parent_descriptor)
    except OSError as recovery_error:
        detail = (
            "backup cleanup failed after recovery became unsafe; NEEDS_CONTEXT: "
            + str(cleanup_error)
        )
        raise PublicationCommitContextError(detail) from recovery_error


def _require_identity(
    parent_descriptor: int,
    name: str,
    expected: DirectoryIdentity,
) -> None:
    if directory_identity(parent_descriptor, name) != expected:
        raise PublicationCommitContextError(
            "publication identity changed during commit; NEEDS_CONTEXT"
        )


__all__ = ("PublicationCommitContextError", "commit_replacement")
