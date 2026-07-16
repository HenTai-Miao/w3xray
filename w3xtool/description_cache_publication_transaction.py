"""Descriptor-anchored transaction for one validated cache stage."""

from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path
from typing import Final

from .description_cache_publication_commit import commit_replacement
from .description_cache_publication_errors import (
    DescriptionCacheConcurrentDestinationError,
    DescriptionCachePublicationError,
)
from .description_cache_publication_fs import (
    DirectoryIdentity as _Identity,
    directory_identity as _directory_identity,
    object_identity as _object_identity,
    remove_directory as _remove_directory,
)
from .trusted_description_cache import VerifiedDescriptionCache


_DIRECTORY_FLAGS: Final = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)
type _Rename = Callable[[int, str, str], None]
type _Validate = Callable[[Path], VerifiedDescriptionCache]
type _Sync = Callable[[int], None]


def publish_valid_stage(
    stage: Path,
    output: Path,
    backup: Path,
    rename_noreplace: _Rename,
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
        return _publish_from_parent(
            parent_descriptor,
            stage,
            output,
            backup,
            rename_noreplace,
            require_valid,
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
    require_valid: _Validate,
    sync_parent: _Sync,
) -> VerifiedDescriptionCache:
    stage_identity = _directory_identity(parent_descriptor, stage.name)
    try:
        rename_noreplace(parent_descriptor, output.name, backup.name)
    except FileNotFoundError:
        return _publish_absent(
            parent_descriptor,
            stage,
            output,
            stage_identity,
            rename_noreplace,
            require_valid,
            sync_parent,
        )
    backup_identity = _directory_identity(parent_descriptor, backup.name)
    try:
        sync_parent(parent_descriptor)
        _ = require_valid(backup)
        _require_identity(parent_descriptor, backup.name, backup_identity)
    except OSError:
        _restore_backup(
            parent_descriptor,
            output.name,
            backup.name,
            backup_identity,
            rename_noreplace,
            sync_parent,
        )
        raise
    try:
        rename_noreplace(parent_descriptor, stage.name, output.name)
    except FileExistsError:
        _reject_takeover(
            parent_descriptor,
            output,
            backup.name,
            backup_identity,
            require_valid,
            sync_parent,
        )
    except OSError:
        _restore_backup(
            parent_descriptor,
            output.name,
            backup.name,
            backup_identity,
            rename_noreplace,
            sync_parent,
        )
        raise
    try:
        sync_parent(parent_descriptor)
        verified = require_valid(output)
        _require_identity(parent_descriptor, output.name, stage_identity)
    except OSError:
        _remove_directory(parent_descriptor, output.name, stage_identity)
        sync_parent(parent_descriptor)
        _restore_backup(
            parent_descriptor,
            output.name,
            backup.name,
            backup_identity,
            rename_noreplace,
            sync_parent,
        )
        raise
    return commit_replacement(
        parent_descriptor,
        output,
        stage_identity,
        backup,
        backup_identity,
        verified,
        _remove_directory,
        rename_noreplace,
        require_valid,
        sync_parent,
    )


def _publish_absent(
    parent_descriptor: int,
    stage: Path,
    output: Path,
    stage_identity: _Identity,
    rename_noreplace: _Rename,
    require_valid: _Validate,
    sync_parent: _Sync,
) -> VerifiedDescriptionCache:
    try:
        rename_noreplace(parent_descriptor, stage.name, output.name)
    except FileExistsError:
        _reject_takeover(
            parent_descriptor,
            output,
            None,
            None,
            require_valid,
            sync_parent,
        )
    try:
        sync_parent(parent_descriptor)
        verified = require_valid(output)
        _require_identity(parent_descriptor, output.name, stage_identity)
    except OSError:
        _remove_directory(parent_descriptor, output.name, stage_identity)
        sync_parent(parent_descriptor)
        raise
    return verified


def _reject_takeover(
    parent_descriptor: int,
    output: Path,
    backup_name: str | None,
    backup_identity: _Identity | None,
    require_valid: _Validate,
    sync_parent: _Sync,
) -> None:
    before = _object_identity(parent_descriptor, output.name)
    try:
        _ = require_valid(output)
    except OSError as exc:
        takeover_detail = f"foreign destination: {exc}"
    else:
        takeover_detail = "externally published owned destination"
    after = _object_identity(parent_descriptor, output.name)
    if before != after:
        raise DescriptionCacheConcurrentDestinationError(
            "concurrent destination changed again; isolated backup retained"
        )
    if backup_name is not None and backup_identity is not None:
        _remove_directory(parent_descriptor, backup_name, backup_identity)
        sync_parent(parent_descriptor)
    raise DescriptionCacheConcurrentDestinationError(
        f"destination was acquired by another writer: {takeover_detail}"
    )


def _restore_backup(
    parent_descriptor: int,
    output_name: str,
    backup_name: str,
    backup_identity: _Identity,
    rename_noreplace: _Rename,
    sync_parent: _Sync,
) -> None:
    _require_identity(parent_descriptor, backup_name, backup_identity)
    rename_noreplace(parent_descriptor, backup_name, output_name)
    sync_parent(parent_descriptor)


def _require_identity(
    parent_descriptor: int,
    name: str,
    expected: _Identity,
) -> None:
    if _directory_identity(parent_descriptor, name) != expected:
        raise DescriptionCacheConcurrentDestinationError(
            "isolated publication object changed identity"
        )


__all__ = (
    "DescriptionCacheConcurrentDestinationError",
    "DescriptionCachePublicationError",
    "publish_valid_stage",
)
