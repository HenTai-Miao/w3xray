"""Atomic owned publication for migrated trusted description evidence."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path
import shutil
from uuid import uuid4

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
from .durable_io import sync_directory
from .safe_output import write_text_safely
from .safe_output_models import SafeWriteStatus
from .trusted_description_cache import (
    TrustedDescriptionCacheError,
    VerifiedDescriptionCache,
    load_trusted_description_cache,
)


class DescriptionCachePublicationError(OSError):
    """A trusted cache could not be published without partial evidence."""

    __slots__ = ("detail",)

    detail: str

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail

    def __str__(self) -> str:
        return self.detail


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
        _require_valid(stage)
        _publish_valid_stage(stage, output, backup)
        return _require_valid(output).cache
    finally:
        if stage.is_dir() and not stage.is_symlink():
            shutil.rmtree(stage)
            sync_directory(output.parent)


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


def _publish_valid_stage(stage: Path, output: Path, backup: Path) -> None:
    if output.exists() or output.is_symlink():
        _ = _require_valid(output)
        output.replace(backup)
        try:
            sync_directory(output.parent)
            _replace_stage(stage, output)
            sync_directory(output.parent)
            _ = _require_valid(output)
        except OSError as exc:
            _restore_backup(output, backup)
            if isinstance(exc, DescriptionCachePublicationError):
                raise
            raise DescriptionCachePublicationError(str(exc)) from exc
        shutil.rmtree(backup)
        sync_directory(output.parent)
        return
    try:
        _replace_stage(stage, output)
    except OSError as exc:
        raise DescriptionCachePublicationError(str(exc)) from exc
    sync_directory(output.parent)


def _replace_stage(stage: Path, destination: Path) -> None:
    stage.replace(destination)


def _restore_backup(output: Path, backup: Path) -> None:
    if output.is_dir() and not output.is_symlink():
        shutil.rmtree(output)
    backup.replace(output)
    sync_directory(output.parent)


__all__ = ("DescriptionCachePublicationError", "publish_description_cache")
