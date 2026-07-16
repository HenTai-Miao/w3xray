"""Identity-proven restoration for an exchanged cache generation."""

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
from .trusted_description_cache import VerifiedDescriptionCache


type Exchange = Callable[[int, str, str], None]
type Remove = Callable[[int, str, DirectoryIdentity], None]
type Rename = Callable[[int, str, str], None]
type Sync = Callable[[int], None]
type Validate = Callable[[Path], VerifiedDescriptionCache]


def restore_previous_generation(
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
    """Restore a proven previous generation without exposing an absent output."""
    try:
        _require_valid_identity(recovery, previous_identity, require_valid)
        _require_identity(parent_descriptor, output.name, staged_identity)
        rename_exchange(parent_descriptor, output.name, recovery.name)
        _require_identity(parent_descriptor, output.name, previous_identity)
        _require_identity(parent_descriptor, recovery.name, staged_identity)
        sync_parent(parent_descriptor)
        _require_valid_identity(output, previous_identity, require_valid)
        _require_valid_identity(recovery, staged_identity, require_valid)
        _remove_recovered_stage(
            parent_descriptor,
            recovery,
            stage,
            staged_identity,
            rename_noreplace,
            require_valid,
            remove_directory,
            sync_parent,
        )
    except PublicationCommitContextError:
        raise
    except OSError as exc:
        raise PublicationCommitContextError(f"{detail}; NEEDS_CONTEXT") from exc


def _remove_recovered_stage(
    parent_descriptor: int,
    recovery: Path,
    stage: Path,
    staged_identity: DirectoryIdentity,
    rename_noreplace: Rename,
    require_valid: Validate,
    remove_directory: Remove,
    sync_parent: Sync,
) -> None:
    private = recovery
    if recovery.name != stage.name:
        rename_noreplace(parent_descriptor, recovery.name, stage.name)
        private = stage
        _require_identity(parent_descriptor, private.name, staged_identity)
        sync_parent(parent_descriptor)
    _require_valid_identity(private, staged_identity, require_valid)
    remove_directory(parent_descriptor, private.name, staged_identity)
    sync_parent(parent_descriptor)


def _require_valid_identity(
    path: Path,
    expected: DirectoryIdentity,
    require_valid: Validate,
) -> None:
    _ = require_valid(path)
    parent_descriptor = _open_parent(path)
    try:
        _require_identity(parent_descriptor, path.name, expected)
    finally:
        _close(parent_descriptor)


def _require_identity(
    parent_descriptor: int,
    name: str,
    expected: DirectoryIdentity,
) -> None:
    if directory_identity(parent_descriptor, name) != expected:
        raise PublicationCommitContextError(
            "publication identity changed during recovery; NEEDS_CONTEXT"
        )


def _open_parent(path: Path) -> int:
    import os

    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    return os.open(path.parent, flags)


def _close(descriptor: int) -> None:
    import os

    os.close(descriptor)


__all__ = ("restore_previous_generation",)
