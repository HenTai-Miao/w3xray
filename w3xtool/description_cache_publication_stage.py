"""Identity capture and final cleanup for one private cache stage."""

from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path
from typing import Final

from .description_cache_publication_errors import PublicationCommitContextError
from .description_cache_publication_fs import (
    DirectoryIdentity,
    directory_identity,
    remove_directory,
)
from .description_cache_publication_parent import (
    parent_descriptor_identity,
    require_parent_identity,
)


_DIRECTORY_FLAGS: Final = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)
type Sync = Callable[[int], None]


def capture_stage_identity(
    stage: Path,
) -> tuple[DirectoryIdentity, DirectoryIdentity]:
    """Capture the exact parent and stage identities before publication."""
    parent_descriptor = os.open(stage.parent, _DIRECTORY_FLAGS)
    try:
        return (
            parent_descriptor_identity(parent_descriptor),
            directory_identity(parent_descriptor, stage.name),
        )
    finally:
        os.close(parent_descriptor)


def remove_stage(
    stage: Path,
    parent_identity: DirectoryIdentity,
    stage_identity: DirectoryIdentity,
    sync_parent: Sync,
) -> None:
    """Remove only the captured stage below its still-identical parent."""
    try:
        parent_descriptor = os.open(stage.parent, _DIRECTORY_FLAGS)
    except OSError as exc:
        raise PublicationCommitContextError(
            "cannot reopen publication parent for stage cleanup; NEEDS_CONTEXT"
        ) from exc
    try:
        require_parent_identity(parent_descriptor, stage.parent, parent_identity)
        try:
            remove_directory(parent_descriptor, stage.name, stage_identity)
        except FileNotFoundError:
            return
        sync_parent(parent_descriptor)
    except PublicationCommitContextError:
        raise
    except OSError as exc:
        raise PublicationCommitContextError(
            "cannot prove final stage cleanup; NEEDS_CONTEXT"
        ) from exc
    finally:
        os.close(parent_descriptor)


__all__ = ("capture_stage_identity", "remove_stage")
