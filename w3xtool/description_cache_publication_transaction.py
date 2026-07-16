"""Descriptor-anchored transaction for one validated cache stage."""

from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path
from typing import Final

from .description_cache_publication_absent import publish_absent
from .description_cache_publication_errors import (
    DescriptionCacheConcurrentDestinationError,
    DescriptionCachePublicationError,
)
from .description_cache_publication_fs import (
    DirectoryIdentity,
    directory_identity as _directory_identity,
    remove_directory as _remove_directory,
)
from .description_cache_publication_parent import ParentBoundValidator
from .description_cache_publication_replacement import publish_replacement
from .trusted_description_cache import VerifiedDescriptionCache


_DIRECTORY_FLAGS: Final = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)
type _Rename = Callable[[int, str, str], None]
type _Exchange = Callable[[int, str, str], None]
type _Remove = Callable[[int, str, DirectoryIdentity], None]
type _Validate = Callable[[Path], VerifiedDescriptionCache]
type _Sync = Callable[[int], None]


def publish_valid_stage(
    stage: Path,
    output: Path,
    backup: Path,
    parent_identity: DirectoryIdentity,
    rename_noreplace: _Rename,
    rename_exchange: _Exchange,
    require_valid: _Validate,
    sync_parent: _Sync,
) -> VerifiedDescriptionCache:
    """Publish a valid stage without consuming a concurrent destination."""
    if stage.parent != output.parent or backup.parent != output.parent:
        raise DescriptionCachePublicationError("publication paths have mixed parents")
    try:
        parent_descriptor = os.open(output.parent, _DIRECTORY_FLAGS)
    except OSError as exc:
        raise DescriptionCachePublicationError(str(exc)) from exc
    try:
        binding = ParentBoundValidator(
            parent_descriptor,
            output.parent,
            parent_identity,
            require_valid,
            _remove_directory,
        )
        binding.require_current_parent()
        return _publish_from_parent(
            parent_descriptor,
            stage,
            output,
            backup,
            rename_noreplace,
            rename_exchange,
            binding.require_valid,
            binding.remove_directory,
            sync_parent,
        )
    except DescriptionCachePublicationError:
        raise
    except OSError as exc:
        raise DescriptionCachePublicationError(str(exc)) from exc
    finally:
        os.close(parent_descriptor)


def _publish_from_parent(
    parent_descriptor: int,
    stage: Path,
    output: Path,
    backup: Path,
    rename_noreplace: _Rename,
    rename_exchange: _Exchange,
    require_valid: _Validate,
    remove_directory: _Remove,
    sync_parent: _Sync,
) -> VerifiedDescriptionCache:
    stage_identity = _directory_identity(parent_descriptor, stage.name)
    _ = require_valid(stage)
    _require_identity(parent_descriptor, stage.name, stage_identity)
    try:
        output_identity = _directory_identity(parent_descriptor, output.name)
    except FileNotFoundError:
        return publish_absent(
            parent_descriptor,
            stage,
            output,
            stage_identity,
            rename_noreplace,
            require_valid,
            remove_directory,
            sync_parent,
        )
    _ = require_valid(output)
    _require_identity(parent_descriptor, output.name, output_identity)
    return publish_replacement(
        parent_descriptor,
        stage,
        stage_identity,
        output,
        output_identity,
        backup,
        rename_exchange,
        rename_noreplace,
        require_valid,
        remove_directory,
        sync_parent,
    )


def _require_identity(
    parent_descriptor: int,
    name: str,
    expected: tuple[int, int],
) -> None:
    if _directory_identity(parent_descriptor, name) != expected:
        raise DescriptionCacheConcurrentDestinationError(
            "existing cache changed identity during validation"
        )


__all__ = (
    "DescriptionCacheConcurrentDestinationError",
    "DescriptionCachePublicationError",
    "publish_valid_stage",
)
