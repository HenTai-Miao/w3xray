"""Second-level resource references with complete source/read diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .batch_tsv import format_tsv_rows
from .resource_candidates import (
    ResourceCandidateReport,
    build_resource_candidate_report,
)
from .resources import resource_kind

if TYPE_CHECKING:
    from .api import MapData


@dataclass(frozen=True, slots=True)
class ResourceContentReference:
    source_path: str
    target_path: str
    target_kind: str
    detail: str
    state: str = ""
    line: int = 0
    offset: int = 0
    end_offset: int = 0
    raw: str = ""
    source_fingerprint: str = ""
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ResourceContentReferenceReport:
    items: tuple[ResourceContentReference, ...]
    candidates: ResourceCandidateReport = ResourceCandidateReport(())


def build_resource_content_references(md: MapData) -> ResourceContentReferenceReport:
    """Follow every readable declared resource body, sharing archive verification."""
    report = build_resource_candidate_report(md)
    refs = tuple(
        ResourceContentReference(
            item.source.replace("/", "\\").lower(),
            item.path.replace("/", "\\").lower(),
            resource_kind(item.path),
            "素材/配置文本内容",
            item.state,
            item.line,
            item.offset,
            item.end_offset,
            item.raw,
            item.source_fingerprint,
            item.diagnostics,
        )
        for item in report.items
        if item.source_kind == "asset-body"
        and item.path.replace("/", "\\").lower()
        != item.source.replace("/", "\\").lower()
    )
    return ResourceContentReferenceReport(refs, report)


def format_resource_content_references_tsv(
    report: ResourceContentReferenceReport,
) -> str:
    """Retain complete cells, duplicate occurrences, provenance and failures."""
    rows = [
        (
            "来源文件",
            "引用路径",
            "引用类型",
            "说明",
            "状态",
            "行",
            "偏移",
            "结束偏移",
            "原始证据",
            "来源指纹",
            "诊断",
        )
    ]
    rows.extend(
        (
            item.source_path,
            item.target_path,
            item.target_kind,
            item.detail,
            item.state,
            str(item.line),
            str(item.offset),
            str(item.end_offset),
            item.raw,
            item.source_fingerprint,
            "\n".join(item.diagnostics),
        )
        for item in report.items
    )
    rows.extend(
        (
            item.source,
            "",
            "",
            "来源诊断",
            "diagnostic",
            "",
            "",
            "",
            "",
            "",
            item.stage + ": " + item.detail,
        )
        for item in report.candidates.diagnostics
    )
    return format_tsv_rows(rows)
