"""Bind publication validation and cleanup to one held parent directory."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import os
from pathlib import Path
import stat

from .description_cache_publication_errors import PublicationCommitContextError
from .description_cache_publication_fs import DirectoryIdentity
from .trusted_description_cache import VerifiedDescriptionCache


type Validate = Callable[[Path], VerifiedDescriptionCache]
type Remove = Callable[[int, str, DirectoryIdentity], None]


def parent_descriptor_identity(parent_descriptor: int) -> DirectoryIdentity:
    """Return the directory identity held by one open descriptor."""
    try:
        details = os.fstat(parent_descriptor)
    except OSError as exc:
        raise PublicationCommitContextError(
            "publication parent descriptor is unreadable; NEEDS_CONTEXT"
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
            "publication parent pathname is unavailable; NEEDS_CONTEXT"
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


@dataclass(frozen=True, slots=True)
class ParentBoundValidator:
    """Validate paths and remove owned objects only below one proven parent."""

    parent_descriptor: int
    parent: Path
    parent_identity: DirectoryIdentity
    validator: Validate
    remover: Remove

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
            verified = self.validator(path)
        except OSError as validation_error:
            try:
                self.require_current_parent()
            except PublicationCommitContextError as context_error:
                raise context_error from validation_error
            raise
        self.require_current_parent()
        return verified

    def remove_directory(
        self,
        parent_descriptor: int,
        name: str,
        expected: DirectoryIdentity,
    ) -> None:
        """Remove one exact owned object only after re-proving its parent."""
        if parent_descriptor != self.parent_descriptor:
            raise PublicationCommitContextError(
                "cleanup escaped the held publication parent; NEEDS_CONTEXT"
            )
        self.require_current_parent()
        self.remover(parent_descriptor, name, expected)


__all__ = (
    "ParentBoundValidator",
    "parent_descriptor_identity",
    "require_parent_identity",
)
