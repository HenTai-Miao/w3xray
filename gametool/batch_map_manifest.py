"""Finalize one staged map with a manifest-bound ownership marker."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
from pathlib import Path
from typing import override

from .batch_manifest_io import format_map_manifest, format_ownership_record
from .batch_manifest_models import (
    CONTENT_MANIFEST_NAME,
    OWNERSHIP_MARKER_NAME,
    OWNERSHIP_SCHEMA_VERSION,
    OwnershipRecord,
)
from .batch_manifest_validation import build_map_manifest
from .batch_models import MapBatchResult
from .safe_output import write_text_safely
from .safe_output_models import SafeWriteStatus


@dataclass(frozen=True, slots=True)
class BatchManifestPublicationError(OSError):
    artifact: str
    detail: str

    @override
    def __str__(self) -> str:
        return f"cannot write {self.artifact}: {self.detail}"


def finalize_map_manifest(
    stage: Path,
    result: MapBatchResult,
    transaction_id: str,
) -> MapBatchResult:
    """Write manifest then ownership marker and return their persisted identity."""
    manifest = build_map_manifest(stage, result, transaction_id)
    manifest_text = format_map_manifest(manifest)
    manifest_sha256 = hashlib.sha256(manifest_text.encode()).hexdigest()
    _write(stage, CONTENT_MANIFEST_NAME, manifest_text)
    ownership = OwnershipRecord(
        OWNERSHIP_SCHEMA_VERSION,
        result.source.sha256,
        manifest_sha256,
        transaction_id,
    )
    _write(stage, OWNERSHIP_MARKER_NAME, format_ownership_record(ownership))
    return replace(
        result,
        manifest_sha256=manifest_sha256,
        published_bytes=manifest.total_size,
    )


def _write(stage: Path, name: str, text: str) -> None:
    write = write_text_safely(str(stage), name, text)
    if write.status is not SafeWriteStatus.WRITTEN:
        raise BatchManifestPublicationError(name, write.error or write.status.value)
