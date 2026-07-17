"""Identity proof for one held publication parent."""

from __future__ import annotations

import os
from pathlib import Path
import stat

from .description_cache_publication_errors import PublicationCommitContextError
from .description_cache_publication_fs import DirectoryIdentity


def parent_descriptor_identity(parent_descriptor: int) -> DirectoryIdentity:
    """Return the directory identity held by one open descriptor."""
    try:
        details = os.fstat(parent_descriptor)
    except OSError as exc:
        raise PublicationCommitContextError(
            "publication parent descriptor is unreadable; NEEDS_CONTEXT",
            failures=(exc,),
        ) from exc
    if not stat.S_ISDIR(details.st_mode):
        raise PublicationCommitContextError(
            "publication parent descriptor is not a directory; NEEDS_CONTEXT"
        )
    return details.st_dev, details.st_ino


def require_parent_identity(
    parent_descriptor: int,
    parent: Path,
    expected: DirectoryIdentity,
) -> None:
    """Prove a pathname still resolves to the exact held parent directory."""
    held = parent_descriptor_identity(parent_descriptor)
    try:
        named = os.stat(parent, follow_symlinks=False)
    except OSError as exc:
        raise PublicationCommitContextError(
            "publication parent pathname is unavailable; NEEDS_CONTEXT",
            failures=(exc,),
        ) from exc
    named_identity = named.st_dev, named.st_ino
    if (
        not stat.S_ISDIR(named.st_mode)
        or held != expected
        or named_identity != expected
    ):
        raise PublicationCommitContextError(
            "publication parent identity changed; NEEDS_CONTEXT"
        )


__all__ = ("parent_descriptor_identity", "require_parent_identity")
