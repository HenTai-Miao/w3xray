"""Recoverable cleanup and explicit commit for cache replacement."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .description_cache_publication_errors import (
    PublicationCommitContextError,
)
from .description_cache_publication_fs import (
    DirectoryIdentity,
    directory_identity,
)
from .description_cache_publication_recovery import restore_previous_generation
from .trusted_description_cache import VerifiedDescriptionCache


type _Exchange = Callable[[int, str, str], None]
type _Remove = Callable[[int, str, DirectoryIdentity], None]
type _Rename = Callable[[int, str, str], None]
type _Sync = Callable[[int], None]
type _Validate = Callable[[Path], VerifiedDescriptionCache]


def commit_replacement(
    parent_descriptor: int,
    output: Path,
    output_identity: DirectoryIdentity,
    backup: Path,
    backup_identity: DirectoryIdentity,
    stage: Path,
    verified: VerifiedDescriptionCache,
    remove_directory: _Remove,
    rename_exchange: _Exchange,
    rename_noreplace: _Rename,
    require_valid: _Validate,
    sync_parent: _Sync,
) -> VerifiedDescriptionCache:
    """Rollback recoverable cleanup errors, then cross one commit point."""
    try:
        remove_directory(parent_descriptor, backup.name, backup_identity)
    except OSError as cleanup_error:
        restore_previous_generation(
            parent_descriptor,
            output,
            output_identity,
            backup,
            backup_identity,
            stage,
            rename_exchange,
            rename_noreplace,
            require_valid,
            remove_directory,
            sync_parent,
            f"backup cleanup failed: {cleanup_error}",
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


def _require_identity(
    parent_descriptor: int,
    name: str,
    expected: DirectoryIdentity,
) -> None:
    try:
        actual = directory_identity(parent_descriptor, name)
    except OSError as exc:
        raise PublicationCommitContextError(
            "publication identity cannot be proven during commit; NEEDS_CONTEXT"
        ) from exc
    if actual != expected:
        raise PublicationCommitContextError(
            "publication identity changed during commit; NEEDS_CONTEXT"
        )


__all__ = ("PublicationCommitContextError", "commit_replacement")
