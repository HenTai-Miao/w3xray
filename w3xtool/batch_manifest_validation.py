"""Build and verify immutable per-map publication manifests."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Final

from .batch_manifest_inventory import (
    ManifestInventoryError,
    build_artifact_inventory,
    snapshot_artifact_inventory,
)
from .batch_manifest_io import parse_map_manifest, parse_ownership_record
from .batch_manifest_models import (
    CONTENT_MANIFEST_NAME,
    OWNERSHIP_MARKER_NAME,
    REQUIRED_MAP_REPORTS,
    ManifestArtifact,
    ManifestResultSummary,
    MapContentManifest,
    PublicationValidation,
)
from .batch_models import MapBatchResult
from .batch_report_validation import validate_report_summaries
from .bounded_file import read_bounded_regular_file


_MAX_MANIFEST_BYTES: Final = 64 * 1024 * 1024
_MAX_MARKER_BYTES: Final = 64 * 1024
_REPORT_NAMES: Final = frozenset(REQUIRED_MAP_REPORTS)


def build_map_manifest(
    stage: Path,
    result: MapBatchResult,
    transaction_id: str,
) -> MapContentManifest:
    """Hash every staged artifact in bounded chunks and freeze its inventory."""
    artifacts = _inventory(stage)
    return MapContentManifest(
        schema_version=1,
        transaction_id=transaction_id,
        source=result.source,
        dependency_fingerprint=result.dependency_fingerprint,
        result=summary_from_result(result),
        artifacts=artifacts,
        total_size=sum(item.size for item in artifacts),
    )


def summary_from_result(result: MapBatchResult) -> ManifestResultSummary:
    """Select exactly the persisted fields reconciled by report validation."""
    return ManifestResultSummary(
        stage=result.stage,
        state=result.state,
        publication_result=result.publication_result,
        archive_integrity=result.archive_integrity,
        knowledge_evidence=result.knowledge_evidence,
        knowledge_gap_reasons=result.knowledge_gap_reasons,
        object_count=result.object_count,
        description_counts=result.description_counts,
        named_icon_count=result.named_icon_count,
        anonymous_icon_count=result.anonymous_icon_count,
        original_written_count=result.original_written_count,
        png_written_count=result.png_written_count,
        icon_failure_count=result.icon_failure_count,
        restricted_block_count=result.restricted_block_count,
        raw_block_count=result.raw_block_count,
        damaged_block_count=result.damaged_block_count,
        relation_counts=result.relation_counts,
        relation_incomplete_count=result.relation_incomplete_count,
        valid_icon_reference_count=result.valid_icon_reference_count,
        resolved_icon_reference_count=result.resolved_icon_reference_count,
        filtered_icon_field_count=result.filtered_icon_field_count,
        unresolved_icon_count=result.unresolved_icon_count,
        unresolved_icon_reference_count=result.unresolved_icon_reference_count,
        anonymous_read_failure_count=result.anonymous_read_failure_count,
        original_write_failure_count=result.original_write_failure_count,
        png_failure_count=result.png_failure_count,
        current_source_unavailable_count=result.current_source_unavailable_count,
        current_source_conflict_count=result.current_source_conflict_count,
        relation_partial_count=result.relation_partial_count,
        unresolved_endpoint_count=result.unresolved_endpoint_count,
        client_unavailable_icon_count=result.client_unavailable_icon_count,
    )


def verify_map_publication(
    directory: Path,
    expected: MapBatchResult | None = None,
    *,
    requested_reports: frozenset[str] = frozenset(),
) -> PublicationValidation:
    """Re-read ownership, manifest, files, and report summaries for reuse."""
    if not requested_reports <= _REPORT_NAMES:
        return _invalid("invalid_report_request")
    if directory.is_symlink() or not directory.is_dir():
        return _invalid("unsafe_directory")
    marker_path = directory / OWNERSHIP_MARKER_NAME
    manifest_path = directory / CONTENT_MANIFEST_NAME
    try:
        marker_bytes, _marker_identity = read_bounded_regular_file(
            marker_path, _MAX_MARKER_BYTES
        )
        manifest_bytes, _manifest_identity = read_bounded_regular_file(
            manifest_path, _MAX_MANIFEST_BYTES
        )
        marker = parse_ownership_record(marker_bytes.decode("utf-8"))
        manifest = parse_map_manifest(manifest_bytes.decode("utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        return _invalid("invalid_publication_metadata", str(exc))
    manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
    if marker.manifest_sha256 != manifest_digest:
        return _invalid("marker_manifest_hash_mismatch")
    if (
        marker.source_sha256 != manifest.source.sha256
        or marker.transaction_id != manifest.transaction_id
    ):
        return _invalid("ownership_manifest_mismatch")
    if expected is not None and not _matches_expected(
        expected, manifest, manifest_digest
    ):
        return _invalid("result_summary_mismatch")
    try:
        inventory, reports = snapshot_artifact_inventory(directory)
    except ManifestInventoryError as exc:
        return _invalid(exc.code, exc.detail, exc.relative_path)
    actual_by_path = {item.relative_path: item for item in inventory}
    expected_by_path = {item.relative_path: item for item in manifest.artifacts}
    if actual_by_path.keys() != expected_by_path.keys():
        return _invalid("artifact_set_mismatch")
    for relative, artifact in expected_by_path.items():
        actual = actual_by_path[relative]
        if actual.size != artifact.size:
            return _invalid("artifact_size_mismatch", relative_path=relative)
        if actual.sha256 != artifact.sha256:
            return _invalid("artifact_hash_mismatch", relative_path=relative)
    if not set(REQUIRED_MAP_REPORTS).issubset(expected_by_path):
        return _invalid("required_report_missing")
    try:
        mismatch = validate_report_summaries(reports, manifest.result)
    except (OSError, UnicodeError, ValueError) as exc:
        return _invalid("report_schema_mismatch", str(exc))
    if mismatch is not None:
        return _invalid("result_summary_mismatch", mismatch)
    return PublicationValidation(
        True,
        "valid",
        manifest_sha256=manifest_digest,
        published_bytes=manifest.total_size,
        manifest=manifest,
        reports=reports.select(requested_reports),
    )


def _inventory(root: Path) -> tuple[ManifestArtifact, ...]:
    try:
        return build_artifact_inventory(root)
    except ManifestInventoryError as exc:
        raise ValueError(exc.detail or exc.code) from exc


def _matches_expected(
    expected: MapBatchResult,
    manifest: MapContentManifest,
    manifest_digest: str,
) -> bool:
    return (
        expected.source == manifest.source
        and expected.dependency_fingerprint == manifest.dependency_fingerprint
        and expected.manifest_sha256 == manifest_digest
        and summary_from_result(expected) == manifest.result
        and expected.published_bytes == manifest.total_size
    )


def _invalid(
    code: str,
    detail: str = "",
    relative_path: str = "",
) -> PublicationValidation:
    return PublicationValidation(False, code, detail, relative_path)
