"""Safe inventory and single-open report snapshots for map manifests."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Final
from unicodedata import normalize

from .batch_manifest_models import (
    CONTENT_MANIFEST_NAME,
    OWNERSHIP_MARKER_NAME,
    REQUIRED_MAP_REPORTS,
    ArtifactKind,
    ManifestArtifact,
    VerifiedReportPayload,
    VerifiedReportSet,
)
from .bounded_file import read_bounded_regular_file, sha256_regular_file
from .safe_output import safe_relative_path


_MAX_REPORT_BYTES: Final = 512 * 1024 * 1024
_MAX_TOTAL_REPORT_BYTES: Final = 512 * 1024 * 1024
_METADATA_NAMES: Final = frozenset((CONTENT_MANIFEST_NAME, OWNERSHIP_MARKER_NAME))
_REPORT_NAMES: Final = frozenset(REQUIRED_MAP_REPORTS)


class ManifestInventoryError(ValueError):
    """One publication artifact cannot be safely inventoried."""

    __slots__ = ("code", "detail", "relative_path")

    def __init__(self, code: str, detail: str = "", relative_path: str = "") -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail
        self.relative_path = relative_path


def build_artifact_inventory(root: Path) -> tuple[ManifestArtifact, ...]:
    """Hash a trusted staging inventory without retaining report payloads."""
    artifacts, _reports = _inventory(root, snapshot_reports=False)
    return artifacts


def snapshot_artifact_inventory(
    root: Path,
) -> tuple[tuple[ManifestArtifact, ...], VerifiedReportSet]:
    """Hash reports from their bounded snapshot and stream other artifacts."""
    return _inventory(root, snapshot_reports=True)


def _inventory(
    root: Path,
    *,
    snapshot_reports: bool,
) -> tuple[tuple[ManifestArtifact, ...], VerifiedReportSet]:
    artifacts: list[ManifestArtifact] = []
    reports: list[VerifiedReportPayload] = []
    identities: set[str] = set()
    report_bytes = 0
    for path in sorted(root.rglob("*"), key=lambda item: str(item).casefold()):
        relative = _relative(root, path)
        if path.is_symlink():
            raise ManifestInventoryError("unsafe_artifact", relative_path=relative)
        if path.is_dir() or relative in _METADATA_NAMES:
            continue
        parsed = safe_relative_path(relative)
        if parsed is None or parsed.as_posix() != relative:
            raise ManifestInventoryError("unsafe_artifact", relative_path=relative)
        identity = normalize("NFC", relative).casefold()
        if identity in identities:
            raise ManifestInventoryError(
                "duplicate artifact path", relative_path=relative
            )
        identities.add(identity)
        try:
            if snapshot_reports and relative in _REPORT_NAMES:
                remaining = _MAX_TOTAL_REPORT_BYTES - report_bytes
                content, file_identity = read_bounded_regular_file(
                    path, min(_MAX_REPORT_BYTES, remaining)
                )
                report_bytes += len(content)
                digest = hashlib.sha256(content).hexdigest()
                reports.append(VerifiedReportPayload(relative, content))
            else:
                digest, file_identity = sha256_regular_file(path)
        except OSError as exc:
            raise ManifestInventoryError("unsafe_artifact", str(exc), relative) from exc
        artifacts.append(
            ManifestArtifact(
                relative,
                _artifact_kind(relative),
                file_identity.size,
                digest,
            )
        )
    ordered = tuple(sorted(artifacts, key=lambda item: item.relative_path.casefold()))
    return ordered, VerifiedReportSet(tuple(reports))


def _artifact_kind(relative: str) -> ArtifactKind:
    if relative.startswith("图标/原始/"):
        return ArtifactKind.ICON_ORIGINAL
    if relative.startswith("图标/PNG/"):
        return ArtifactKind.ICON_PNG
    if relative in _REPORT_NAMES:
        return ArtifactKind.REPORT
    return ArtifactKind.OTHER


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


__all__ = (
    "ManifestInventoryError",
    "build_artifact_inventory",
    "snapshot_artifact_inventory",
)
