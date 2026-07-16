"""Anchored identity and cleanup primitives for cache publication."""

from __future__ import annotations

import os
import shutil
import stat

from .description_cache_publication_errors import (
    DescriptionCacheConcurrentDestinationError,
    DescriptionCachePublicationError,
)

type DirectoryIdentity = tuple[int, int]


def directory_identity(parent_descriptor: int, name: str) -> DirectoryIdentity:
    """Return one anchored directory identity without following its name."""
    details = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    if not stat.S_ISDIR(details.st_mode):
        raise DescriptionCachePublicationError("publication object is not a directory")
    return details.st_dev, details.st_ino


def object_identity(parent_descriptor: int, name: str) -> DirectoryIdentity:
    """Return one anchored filesystem identity without following its name."""
    details = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    return details.st_dev, details.st_ino


def remove_directory(
    parent_descriptor: int,
    name: str,
    expected: DirectoryIdentity,
) -> None:
    """Remove only the expected anchored directory through symlink-safe rmtree."""
    if not shutil.rmtree.avoids_symlink_attacks:
        raise DescriptionCachePublicationError(
            "anchored private-directory cleanup is unavailable"
        )
    if directory_identity(parent_descriptor, name) != expected:
        raise DescriptionCacheConcurrentDestinationError(
            "isolated publication object changed identity"
        )
    shutil.rmtree(name, dir_fd=parent_descriptor)


__all__ = (
    "DirectoryIdentity",
    "directory_identity",
    "object_identity",
    "remove_directory",
)
