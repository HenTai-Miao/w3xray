"""Immutable contracts for authoritative global batch generations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .batch_global_evidence_models import GlobalEvidenceIndex
from .batch_models import BatchState


GLOBAL_SCHEMA_VERSION: Final = 1
GLOBAL_ROOT_NAME: Final = ".w3xray-global"
GLOBAL_MANIFEST_NAME: Final = "全局清单.json"
GLOBAL_POINTER_NAME: Final = "current.json"
GLOBAL_PAYLOAD_NAMES: Final = (
    "批量提取汇总.tsv",
    "批量提取状态.json",
    "失败与重试.tsv",
    "可信描述缓存.tsv",
    "批量诊断.jsonl",
    "图标缺口汇总.tsv",
    "图标候选绑定.tsv",
    "图标缺口统计.txt",
    "三轴状态汇总.tsv",
)


@dataclass(frozen=True, slots=True)
class GlobalArtifact:
    """One exact global payload bound by size and SHA-256."""

    name: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class GlobalManifest:
    """Deterministic inventory for one immutable global generation."""

    schema_version: int
    generation_id: str
    state_schema_version: int
    artifacts: tuple[GlobalArtifact, ...]
    total_size: int


@dataclass(frozen=True, slots=True)
class GlobalPointer:
    """Small authoritative selector for one validated generation."""

    schema_version: int
    generation_id: str
    manifest_sha256: str


@dataclass(frozen=True, slots=True)
class GlobalGeneration:
    """Validated state and cache payload selected by the current pointer."""

    generation_id: str
    directory: Path
    manifest_sha256: str
    state: BatchState
    cache_text: str
    diagnostics_text: str
    evidence: GlobalEvidenceIndex


class GlobalPublicationError(OSError):
    """A global generation could not be durably published or validated."""

    __slots__ = ("detail",)

    detail: str

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail

    def __str__(self) -> str:
        return self.detail


class GlobalFormatError(ValueError):
    """A global manifest or current pointer violates its strict schema."""

    __slots__ = ("detail",)

    detail: str

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail

    def __str__(self) -> str:
        return self.detail
