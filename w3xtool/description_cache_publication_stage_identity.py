"""Identity proof for one held publication-stage descriptor."""

from __future__ import annotations

import os
import stat

from .description_cache_publication_errors import PublicationCommitContextError
from .description_cache_publication_fs import DirectoryIdentity


def descriptor_identity(descriptor: int) -> DirectoryIdentity:
    """Return the exact directory identity held by one descriptor."""
    details = os.fstat(descriptor)
    if not stat.S_ISDIR(details.st_mode):
        raise PublicationCommitContextError(
            "publication descriptor is not a directory; NEEDS_CONTEXT"
        )
    return details.st_dev, details.st_ino


__all__ = ("descriptor_identity",)
