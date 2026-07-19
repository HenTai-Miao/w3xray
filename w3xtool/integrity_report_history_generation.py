"""Exact payload and manifest construction for one integrity history generation."""

from __future__ import annotations

from dataclasses import dataclass
import os

from .descriptor_open_flags import staged_create_flags
from .integrity_report_history import (
    INTEGRITY_HISTORY_MANIFEST_NAME,
    INTEGRITY_HISTORY_REPORT_NAME,
    INTEGRITY_HISTORY_SCHEMA,
    IntegrityHistoryArtifact,
    IntegrityHistoryError,
    IntegrityHistoryManifest,
    format_integrity_history_manifest,
)
from .integrity_report_history_directory import BoundIntegrityHistoryStage
from .integrity_snapshot_file import snapshot_regular_file
from .integrity_snapshot_models import IntegrityEntry
from .safe_output_chunk_writer import write_chunks_to_descriptor
from .safe_output_publication_identity import FileIdentity


@dataclass(frozen=True, slots=True)
class IntegrityHistoryGenerationProof:
    """Exact report and manifest states required after final publication."""

    report_details: os.stat_result
    report_entry: IntegrityEntry
    manifest_details: os.stat_result
    manifest_entry: IntegrityEntry


def write_integrity_history_generation(
    history: BoundIntegrityHistoryStage,
    destination_name: str,
    expected: FileIdentity,
) -> IntegrityHistoryGenerationProof:
    """Move no names; write and verify the manifest around one archived inode."""
    details = os.stat(
        INTEGRITY_HISTORY_REPORT_NAME,
        dir_fd=history.stage_descriptor,
        follow_symlinks=False,
    )
    if (details.st_dev, details.st_ino) != expected:
        raise IntegrityHistoryError("archived report identity changed before hashing")
    entry = snapshot_regular_file(
        history.stage_descriptor,
        INTEGRITY_HISTORY_REPORT_NAME,
        INTEGRITY_HISTORY_REPORT_NAME,
        history.stage_path / INTEGRITY_HISTORY_REPORT_NAME,
        details,
    )
    manifest = IntegrityHistoryManifest(
        INTEGRITY_HISTORY_SCHEMA,
        history.generation_id,
        destination_name,
        (
            IntegrityHistoryArtifact(
                INTEGRITY_HISTORY_REPORT_NAME,
                entry.size,
                entry.sha256,
            ),
        ),
    )
    payload = format_integrity_history_manifest(manifest).encode("utf-8")
    descriptor = os.open(
        INTEGRITY_HISTORY_MANIFEST_NAME,
        staged_create_flags(),
        0o600,
        dir_fd=history.stage_descriptor,
    )
    try:
        _ = write_chunks_to_descriptor(descriptor, (payload,))
    finally:
        os.close(descriptor)
    manifest_details = os.stat(
        INTEGRITY_HISTORY_MANIFEST_NAME,
        dir_fd=history.stage_descriptor,
        follow_symlinks=False,
    )
    manifest_entry = snapshot_regular_file(
        history.stage_descriptor,
        INTEGRITY_HISTORY_MANIFEST_NAME,
        INTEGRITY_HISTORY_MANIFEST_NAME,
        history.stage_path / INTEGRITY_HISTORY_MANIFEST_NAME,
        manifest_details,
    )
    repeated = snapshot_regular_file(
        history.stage_descriptor,
        INTEGRITY_HISTORY_REPORT_NAME,
        INTEGRITY_HISTORY_REPORT_NAME,
        history.stage_path / INTEGRITY_HISTORY_REPORT_NAME,
        details,
    )
    if repeated != entry:
        raise IntegrityHistoryError("archived report changed around manifest write")
    proof = IntegrityHistoryGenerationProof(
        details,
        entry,
        manifest_details,
        manifest_entry,
    )
    require_integrity_history_generation(history, proof)
    return proof


def require_integrity_history_generation(
    history: BoundIntegrityHistoryStage,
    proof: IntegrityHistoryGenerationProof,
) -> None:
    """Re-hash the exact two-file inventory against its creation proof."""
    if set(os.listdir(history.stage_descriptor)) != {
        INTEGRITY_HISTORY_MANIFEST_NAME,
        INTEGRITY_HISTORY_REPORT_NAME,
    }:
        raise IntegrityHistoryError("unexpected integrity history inventory")
    report = snapshot_regular_file(
        history.stage_descriptor,
        INTEGRITY_HISTORY_REPORT_NAME,
        INTEGRITY_HISTORY_REPORT_NAME,
        history.generation_path / INTEGRITY_HISTORY_REPORT_NAME,
        proof.report_details,
    )
    manifest = snapshot_regular_file(
        history.stage_descriptor,
        INTEGRITY_HISTORY_MANIFEST_NAME,
        INTEGRITY_HISTORY_MANIFEST_NAME,
        history.generation_path / INTEGRITY_HISTORY_MANIFEST_NAME,
        proof.manifest_details,
    )
    if report != proof.report_entry or manifest != proof.manifest_entry:
        raise IntegrityHistoryError("integrity history generation changed")


__all__ = (
    "IntegrityHistoryGenerationProof",
    "require_integrity_history_generation",
    "write_integrity_history_generation",
)
