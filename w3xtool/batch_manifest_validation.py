"""Build and verify immutable per-map publication manifests."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Final
from unicodedata import normalize

from .batch_manifest_io import parse_map_manifest, parse_ownership_record
from .batch_manifest_models import (
    CONTENT_MANIFEST_NAME,
    OWNERSHIP_MARKER_NAME,
    REQUIRED_MAP_REPORTS,
    ArtifactKind,
    ManifestArtifact,
    ManifestResultSummary,
    MapContentManifest,
    PublicationValidation,
)
from .batch_models import MapBatchResult
from .batch_report_validation import validate_report_summaries
from .bounded_file import read_bounded_regular_file, sha256_regular_file
from .safe_output import safe_relative_path


_MAX_MANIFEST_BYTES: Final = 64 * 1024 * 1024
_MAX_MARKER_BYTES: Final = 64 * 1024
_METADATA_NAMES: Final = frozenset((CONTENT_MANIFEST_NAME, OWNERSHIP_MARKER_NAME))


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
        result.stage,
        result.state,
        result.object_count,
        result.description_counts,
        result.named_icon_count,
        result.anonymous_icon_count,
        result.original_written_count,
        result.png_written_count,
        result.icon_failure_count,
        result.restricted_block_count,
        result.relation_counts,
        result.relation_incomplete_count,
    )


def verify_map_publication(
    directory: Path,
    expected: MapBatchResult | None = None,
) -> PublicationValidation:
    """Re-read ownership, manifest, files, and report summaries for reuse."""
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
    inventory = _validated_inventory(directory)
    if isinstance(inventory, PublicationValidation):
        return inventory
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
        mismatch = validate_report_summaries(directory, manifest.result)
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
    )


def _inventory(root: Path) -> tuple[ManifestArtifact, ...]:
    inventory = _validated_inventory(root, reject_metadata=False)
    if isinstance(inventory, PublicationValidation):
        raise ValueError(inventory.detail or inventory.code)
    return inventory


def _validated_inventory(
    root: Path,
    *,
    reject_metadata: bool = True,
) -> tuple[ManifestArtifact, ...] | PublicationValidation:
    artifacts: list[ManifestArtifact] = []
    identities: set[str] = set()
    for path in sorted(root.rglob("*"), key=lambda item: str(item).casefold()):
        if path.is_symlink():
            return _invalid("unsafe_artifact", relative_path=_relative(root, path))
        if path.is_dir():
            continue
        relative = _relative(root, path)
        if relative in _METADATA_NAMES:
            if reject_metadata:
                continue
            continue
        parsed = safe_relative_path(relative)
        if parsed is None or parsed.as_posix() != relative:
            return _invalid("unsafe_artifact", relative_path=relative)
        identity = normalize("NFC", relative).casefold()
        if identity in identities:
            return _invalid("duplicate artifact path", relative_path=relative)
        identities.add(identity)
        try:
            digest, file_identity = sha256_regular_file(path)
        except OSError as exc:
            return _invalid("unsafe_artifact", str(exc), relative)
        artifacts.append(
            ManifestArtifact(
                relative,
                _artifact_kind(relative),
                file_identity.size,
                digest,
            )
        )
    return tuple(sorted(artifacts, key=lambda item: item.relative_path.casefold()))


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


def _artifact_kind(relative: str) -> ArtifactKind:
    if relative.startswith("图标/原始/"):
        return ArtifactKind.ICON_ORIGINAL
    if relative.startswith("图标/PNG/"):
        return ArtifactKind.ICON_PNG
    if relative in REQUIRED_MAP_REPORTS:
        return ArtifactKind.REPORT
    return ArtifactKind.OTHER


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _invalid(
    code: str,
    detail: str = "",
    relative_path: str = "",
) -> PublicationValidation:
    return PublicationValidation(False, code, detail, relative_path)
