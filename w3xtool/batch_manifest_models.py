"""Immutable contracts for one content-addressed map publication."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from .batch_models import MapBatchState, SourceFingerprint


CONTENT_MANIFEST_NAME: Final = "内容清单.json"
OWNERSHIP_MARKER_NAME: Final = ".w3xray-batch-owned"
MANIFEST_SCHEMA_VERSION: Final = 1
OWNERSHIP_SCHEMA_VERSION: Final = 1
REQUIRED_MAP_REPORTS: Final = (
    "地图摘要.txt",
    "图标索引.tsv",
    "对象描述.tsv",
    "图标完整性.txt",
    "描述完整性.txt",
    "对象完整描述.tsv",
    "掉落与获取关系.tsv",
    "装备技能关系.tsv",
    "关系完整性.txt",
)


class ArtifactKind(StrEnum):
    """Closed artifact classes used by validation and diagnostics."""

    REPORT = "report"
    ICON_ORIGINAL = "icon_original"
    ICON_PNG = "icon_png"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class ManifestArtifact:
    """One exact regular file included in a map publication."""

    relative_path: str
    kind: ArtifactKind
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class ManifestResultSummary:
    """Result fields that must agree with reports and persisted state."""

    stage: str
    state: MapBatchState
    object_count: int
    description_counts: tuple[tuple[str, int], ...]
    named_icon_count: int
    anonymous_icon_count: int
    original_written_count: int
    png_written_count: int
    icon_failure_count: int
    restricted_block_count: int
    relation_counts: tuple[tuple[str, int], ...]
    relation_incomplete_count: int


@dataclass(frozen=True, slots=True)
class MapContentManifest:
    """Complete immutable inventory for one published map directory."""

    schema_version: int
    transaction_id: str
    source: SourceFingerprint
    dependency_fingerprint: str
    result: ManifestResultSummary
    artifacts: tuple[ManifestArtifact, ...]
    total_size: int


@dataclass(frozen=True, slots=True)
class OwnershipRecord:
    """Small marker binding source identity to one manifest generation."""

    schema_version: int
    source_sha256: str
    manifest_sha256: str
    transaction_id: str


@dataclass(frozen=True, slots=True)
class PublicationValidation:
    """Typed validation result used by resume, cache, and recovery."""

    valid: bool
    code: str
    detail: str = ""
    relative_path: str = ""
    manifest_sha256: str = ""
    published_bytes: int = 0
    manifest: MapContentManifest | None = None
