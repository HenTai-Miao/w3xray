"""No-replace publication when a trusted-cache destination is absent."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .description_cache_publication_errors import (
    DescriptionCacheConcurrentDestinationError,
)
from .description_cache_publication_fs import (
    DirectoryIdentity,
    object_identity,
    remove_directory,
)
from .trusted_description_cache import VerifiedDescriptionCache


type Rename = Callable[[int, str, str], None]
type Validate = Callable[[Path], VerifiedDescriptionCache]
type Sync = Callable[[int], None]


def publish_absent(
    parent_descriptor: int,
    stage: Path,
    output: Path,
    stage_identity: DirectoryIdentity,
    rename_noreplace: Rename,
    require_valid: Validate,
    sync_parent: Sync,
) -> VerifiedDescriptionCache:
    """Publish a stage only while the public destination remains absent."""
    try:
        rename_noreplace(parent_descriptor, stage.name, output.name)
    except FileExistsError:
        _reject_takeover(parent_descriptor, output, require_valid)
    try:
        sync_parent(parent_descriptor)
        verified = require_valid(output)
        _require_identity(parent_descriptor, output.name, stage_identity)
    except OSError:
        remove_directory(parent_descriptor, output.name, stage_identity)
        sync_parent(parent_descriptor)
        raise
    return verified


def _reject_takeover(
    parent_descriptor: int,
    output: Path,
    require_valid: Validate,
) -> None:
    before = object_identity(parent_descriptor, output.name)
    try:
        _ = require_valid(output)
    except OSError as exc:
        takeover_detail = f"foreign destination: {exc}"
    else:
        takeover_detail = "externally published owned destination"
    after = object_identity(parent_descriptor, output.name)
    if before != after:
        raise DescriptionCacheConcurrentDestinationError(
            "concurrent destination changed again"
        )
    raise DescriptionCacheConcurrentDestinationError(
        f"destination was acquired by another writer: {takeover_detail}"
    )


def _require_identity(
    parent_descriptor: int,
    name: str,
    expected: DirectoryIdentity,
) -> None:
    if object_identity(parent_descriptor, name) != expected:
        raise DescriptionCacheConcurrentDestinationError(
            "published cache changed identity"
        )


__all__ = ("publish_absent",)
