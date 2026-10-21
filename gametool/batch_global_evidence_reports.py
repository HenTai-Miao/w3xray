"""Canonical batch-wide icon evidence and three-axis report rendering."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import PureWindowsPath
from typing import Final, TypedDict

from .batch_global_evidence_models import GlobalEvidenceIndex, GlobalIconGap
from .batch_global_evidence_report_parsing import (
    GLOBAL_ICON_CANDIDATE_HEADER,
    GLOBAL_ICON_GAP_HEADER,
    parse_global_icon_gaps_tsv,
    parse_icon_candidates_tsv,
)
from .batch_models import BatchState, MapBatchResult
from .batch_status import PublicationResult
from .batch_tsv import format_tsv_rows
from .icon_evidence_models import IconGapReason
from .icon_resources import IconObjectReference


AXIS_STATUS_HEADER: Final = (
    "源路径",
    "地图名",
    "SHA256",
    "发布结果",
    "档案完整性",
    "知识证据完整性",
    "知识缺口原因",
    "源覆盖缺口",
    "有效图标引用",
    "已解析图标引用",
    "已过滤非图标字段",
    "具名未解析路径",
    "具名未解析引用",
    "关系部分",
    "受限块",
    "损坏块",
    "原始块",
)


class _ReferenceJson(TypedDict):
    category: str
    rawcode: str
    base: str
    name: str
    field: str
    label: str
    type: str
    source: str
    wts: str
    map: str
    scope: str


def format_global_icon_gaps_tsv(evidence: GlobalEvidenceIndex) -> str:
    """Render one canonical row per source-map and normalized gap path."""
    rows: list[tuple[str, ...]] = [GLOBAL_ICON_GAP_HEADER]
    rows.extend(_gap_row(row) for row in evidence.gaps)
    return format_tsv_rows(rows)


def format_icon_candidates_tsv(evidence: GlobalEvidenceIndex) -> str:
    """Render only non-adopted candidate evidence in deterministic order."""
    rows: list[tuple[str, ...]] = [GLOBAL_ICON_CANDIDATE_HEADER]
    rows.extend(
        (
            row.kind.value,
            row.requested_map_sha256,
            row.requested_path,
            row.anonymous_map_sha256,
            "" if row.anonymous_block_index is None else str(row.anonymous_block_index),
            row.candidate_map_sha256,
            row.candidate_path,
            row.content_sha256,
            "否",
        )
        for row in evidence.candidates
    )
    return format_tsv_rows(rows)


def format_icon_gap_statistics(
    evidence: GlobalEvidenceIndex,
    state: BatchState,
) -> str:
    """Render explicit stable totals and path-derived gap groupings."""
    published = sum(
        result.publication_result is PublicationResult.PUBLISHED
        for result in state.results
    )
    lines = [
        "[总计]",
        f"地图={len(state.results)}",
        f"已发布地图={published}",
        f"具名缺口={len(evidence.gaps)}",
        f"未解析引用={sum(row.reference_count for row in evidence.gaps)}",
        f"具名图标={len(evidence.resolved)}",
        f"匿名图标={len(evidence.anonymous)}",
        f"候选绑定={len(evidence.candidates)}",
    ]
    reason_counts = Counter(row.reason for row in evidence.gaps)
    lines.extend(("", "[主原因]"))
    lines.extend(f"{reason.value}={reason_counts[reason]}" for reason in IconGapReason)
    _append_counts(lines, "顶级命名空间", _namespace_counts(evidence))
    _append_counts(lines, "扩展名", _extension_counts(evidence))
    _append_counts(
        lines,
        "对象分类",
        Counter(
            category for row in evidence.gaps for category in row.object_categories
        ),
    )
    _append_counts(lines, "地图", Counter(row.map_path for row in evidence.gaps))
    return "\n".join(lines) + "\n"


def format_axis_status_tsv(state: BatchState) -> str:
    """Render every result on the three authoritative schema-six axes."""
    rows: list[tuple[str, ...]] = [AXIS_STATUS_HEADER]
    rows.extend(_axis_row(result) for result in sorted(state.results, key=_result_key))
    return format_tsv_rows(rows)


def _gap_row(row: GlobalIconGap) -> tuple[str, ...]:
    references = tuple(_reference_json(item) for item in row.references)
    return (
        row.map_path,
        row.map_sha256,
        row.map_scope,
        row.normalized_path,
        row.reason.value,
        json.dumps(
            tuple(flag.value for flag in row.diagnostics),
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        ";".join(row.object_categories),
        ";".join(row.rawcodes),
        str(row.reference_count),
        json.dumps(references, ensure_ascii=False, separators=(",", ":")),
    )


def _reference_json(reference: IconObjectReference) -> _ReferenceJson:
    return _ReferenceJson(
        category=reference.category,
        rawcode=reference.object_id,
        base=reference.base_id,
        name=reference.object_name,
        field=reference.field_key,
        label=reference.field_label,
        type=reference.field_type,
        source=reference.field_source,
        wts=reference.wts_source,
        map=reference.map_path,
        scope=reference.map_scope,
    )


def _axis_row(result: MapBatchResult) -> tuple[str, ...]:
    return (
        result.source.path,
        result.display_name,
        result.source.sha256,
        result.publication_result.value,
        result.archive_integrity.value,
        result.knowledge_evidence.value,
        ";".join(reason.value for reason in result.knowledge_gap_reasons),
        str(result.source_coverage_gap_count),
        str(result.valid_icon_reference_count),
        str(result.resolved_icon_reference_count),
        str(result.filtered_icon_field_count),
        str(result.unresolved_icon_count),
        str(result.unresolved_icon_reference_count),
        str(result.relation_partial_count),
        str(result.restricted_block_count),
        str(result.damaged_block_count),
        str(result.raw_block_count),
    )


def _namespace_counts(evidence: GlobalEvidenceIndex) -> Counter[str]:
    return Counter(
        row.normalized_path.replace("/", "\\").split("\\", 1)[0]
        for row in evidence.gaps
    )


def _extension_counts(evidence: GlobalEvidenceIndex) -> Counter[str]:
    return Counter(
        PureWindowsPath(row.normalized_path).suffix.casefold() or "(无扩展名)"
        for row in evidence.gaps
    )


def _append_counts(
    lines: list[str],
    label: str,
    counts: Counter[str],
) -> None:
    lines.extend(("", f"[{label}]"))
    lines.extend(
        f"{key}={count}"
        for key, count in sorted(
            counts.items(), key=lambda item: (item[0].casefold(), item[0])
        )
    )


def _result_key(result: MapBatchResult) -> tuple[str, str]:
    return result.source.path.casefold(), result.source.path


__all__ = (
    "AXIS_STATUS_HEADER",
    "GLOBAL_ICON_CANDIDATE_HEADER",
    "GLOBAL_ICON_GAP_HEADER",
    "format_axis_status_tsv",
    "format_global_icon_gaps_tsv",
    "format_icon_candidates_tsv",
    "format_icon_gap_statistics",
    "parse_global_icon_gaps_tsv",
    "parse_icon_candidates_tsv",
)
