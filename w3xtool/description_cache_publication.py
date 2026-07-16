"""Atomic owned publication for migrated trusted description evidence."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
import os
from pathlib import Path
from typing import Final
from uuid import uuid4

from .atomic_rename import rename_exchange, rename_noreplace
from .description_cache_migration_models import (
    DescriptionCacheRejection,
    ProvenDescriptionCandidate,
)
from .description_cache_migration_exports import format_migration_payloads
from .description_cache_models import DescriptionCache
from .description_cache_owned_schema import (
    TRUSTED_DESCRIPTION_CACHE_MANIFEST,
    TRUSTED_DESCRIPTION_CACHE_MARKER,
    TRUSTED_DESCRIPTION_CACHE_SCHEMA,
    TrustedCacheArtifact,
    TrustedCacheManifest,
    format_trusted_cache_manifest,
    format_trusted_cache_marker,
    trusted_content_sha256,
)
from .description_cache_publication_transaction import (
    DescriptionCacheConcurrentDestinationError,
    DescriptionCachePublicationError,
    publish_valid_stage,
)
from .description_cache_publication_commit import PublicationCommitContextError
from .description_cache_publication_fs import DirectoryIdentity
from .description_cache_publication_stage import (
    capture_stage_identity,
    remove_stage,
)
from .durable_io import sync_directory, sync_directory_descriptor
from .safe_output import write_text_safely
from .safe_output_models import SafeWriteStatus
from .trusted_description_cache import (
    TrustedDescriptionCacheError,
    VerifiedDescriptionCache,
    load_trusted_description_cache,
)


_DIRECTORY_FLAGS: Final = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)


def publish_description_cache(
    source_root: Path,
    output: Path,
    accepted: Sequence[ProvenDescriptionCandidate],
    rejections: Sequence[DescriptionCacheRejection],
) -> DescriptionCache:
    """Stage, self-validate, and atomically replace one owned cache."""
    identifier = uuid4().hex
    stage = output.parent / f".w3xray-description-cache-stage-{identifier}"
    backup = output.parent / f".w3xray-description-cache-backup-{identifier}"
    if stage.exists() or stage.is_symlink() or backup.exists() or backup.is_symlink():
        raise DescriptionCachePublicationError(
            "private publication path already exists"
        )
    payloads = format_migration_payloads(accepted, rejections)
    stage.mkdir(mode=0o700)
    parent_identity, stage_identity = capture_stage_identity(stage)
    preserve_stage = False
    try:
        sync_directory(output.parent)
        for name, text in payloads.items():
            _write(stage, name, text)
        artifacts = tuple(
            sorted(
                (
                    TrustedCacheArtifact(
                        name,
                        len(text.encode("utf-8")),
                        hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    )
                    for name, text in payloads.items()
                ),
                key=lambda item: item.name.casefold(),
            )
        )
        manifest = TrustedCacheManifest(
            TRUSTED_DESCRIPTION_CACHE_SCHEMA,
            str(source_root),
            artifacts,
            trusted_content_sha256(artifacts),
        )
        manifest_text = format_trusted_cache_manifest(manifest)
        _write(stage, TRUSTED_DESCRIPTION_CACHE_MANIFEST, manifest_text)
        manifest_digest = hashlib.sha256(manifest_text.encode("utf-8")).hexdigest()
        _write(
            stage,
            TRUSTED_DESCRIPTION_CACHE_MARKER,
            format_trusted_cache_marker(manifest_digest),
        )
        sync_directory(stage)
        try:
            return _publish_valid_stage(
                stage,
                output,
                backup,
                parent_identity,
            ).cache
        except PublicationCommitContextError:
            preserve_stage = True
            raise
    finally:
        if not preserve_stage:
            remove_stage(stage, parent_identity, stage_identity, _sync_parent)


def _write(root: Path, name: str, text: str) -> None:
    result = write_text_safely(str(root), name, text)
    if result.status is not SafeWriteStatus.WRITTEN:
        raise DescriptionCachePublicationError(
            f"cannot publish {name}: {result.error or result.status.value}"
        )


def _require_valid(root: Path) -> VerifiedDescriptionCache:
    try:
        return load_trusted_description_cache(root)
    except TrustedDescriptionCacheError as exc:
        raise DescriptionCachePublicationError(
            f"owned cache is not valid: {exc}"
        ) from exc


def _publish_valid_stage(
    stage: Path,
    output: Path,
    backup: Path,
    parent_identity: DirectoryIdentity,
) -> VerifiedDescriptionCache:
    return publish_valid_stage(
        stage,
        output,
        backup,
        parent_identity,
        _rename_noreplace,
        _rename_exchange,
        _require_valid,
        _sync_parent,
    )


def _rename_noreplace(
    parent_descriptor: int,
    source_name: str,
    destination_name: str,
) -> None:
    rename_noreplace(
        parent_descriptor,
        source_name,
        parent_descriptor,
        destination_name,
    )


def _rename_exchange(
    parent_descriptor: int,
    source_name: str,
    destination_name: str,
) -> None:
    rename_exchange(
        parent_descriptor,
        source_name,
        parent_descriptor,
        destination_name,
    )


def _sync_parent(parent_descriptor: int) -> None:
    sync_directory_descriptor(parent_descriptor)


__all__ = (
    "DescriptionCacheConcurrentDestinationError",
    "DescriptionCachePublicationError",
    "publish_description_cache",
)
