"""Identity-gated name operations for anchored output publication."""

from __future__ import annotations

import errno
import os
import secrets
import stat
from typing import override

from .atomic_rename import rename_noreplace


type FileIdentity = tuple[int, int]


class PublicationIdentityError(OSError):
    """A publication name no longer refers to its claimed inode."""

    __slots__ = ("detail",)

    detail: str

    def __init__(self, detail: str) -> None:
        super().__init__(errno.EBUSY, detail)
        self.detail = detail

    @override
    def __str__(self) -> str:
        return self.detail


def regular_identity(parent_descriptor: int, name: str) -> FileIdentity | None:
    """Return one no-follow regular-file identity, or absence."""
    details = _named_details(parent_descriptor, name)
    if details is None:
        return None
    if not stat.S_ISREG(details.st_mode):
        raise OSError(errno.EINVAL, "unsafe destination changed before publication")
    return details.st_dev, details.st_ino


def object_identity(parent_descriptor: int, name: str) -> FileIdentity | None:
    """Return one no-follow object identity regardless of its file kind."""
    details = _named_details(parent_descriptor, name)
    if details is None:
        return None
    return details.st_dev, details.st_ino


def _named_details(parent_descriptor: int, name: str) -> os.stat_result | None:
    try:
        details = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except NotImplementedError as exc:
        raise PublicationIdentityError(
            "descriptor-relative output stat is unavailable"
        ) from exc
    return details


def claim_name(
    parent_descriptor: int,
    source_name: str,
    claimed_name: str,
    expected: FileIdentity,
) -> None:
    """Atomically move one name to an absent claim and prove its identity."""
    rename_noreplace(
        parent_descriptor,
        source_name,
        parent_descriptor,
        claimed_name,
    )
    if object_identity(parent_descriptor, claimed_name) != expected:
        raise PublicationIdentityError("claimed output identity changed")


def restore_claim(
    parent_descriptor: int,
    claimed_name: str,
    destination_name: str,
) -> str | None:
    """Restore a claimed object without replacing any current destination."""
    try:
        claimed = object_identity(parent_descriptor, claimed_name)
        if claimed is None:
            return "claimed output disappeared before restoration"
        claim_name(parent_descriptor, claimed_name, destination_name, claimed)
    except OSError as exc:
        return str(exc)
    return None


def remove_owned_name(
    parent_descriptor: int,
    name: str,
    expected: FileIdentity,
) -> str | None:
    """Unlink a private name only while it retains the owned identity."""
    try:
        current = object_identity(parent_descriptor, name)
        if current is None:
            return None
        if current != expected:
            return "owned output name changed; concurrent object preserved"
        os.unlink(name, dir_fd=parent_descriptor)
    except OSError as exc:
        return str(exc)
    return None


def private_name(prefix: str) -> str:
    """Return a high-entropy leaf for one atomic no-replace claim."""
    return f".{prefix}-{secrets.token_hex(16)}.tmp"


__all__ = (
    "FileIdentity",
    "PublicationIdentityError",
    "claim_name",
    "object_identity",
    "private_name",
    "regular_identity",
    "remove_owned_name",
    "restore_claim",
)
