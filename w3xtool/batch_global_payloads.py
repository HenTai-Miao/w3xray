"""Build the complete authoritative global payload set before staging."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from .batch_global_evidence import collect_global_evidence
from .batch_global_evidence_models import GlobalEvidenceIndex
from .batch_global_evidence_reports import (
    format_axis_status_tsv,
    format_global_icon_gaps_tsv,
    format_icon_candidates_tsv,
    format_icon_gap_statistics,
)
from .batch_models import BatchState
from .batch_reports import (
    format_batch_state_json,
    format_batch_summary_tsv,
    format_retry_tsv,
    parse_batch_state_json,
)
from .batch_global_models import GlobalPublicationError


@dataclass(frozen=True, slots=True)
class GlobalPayloadBundle:
    """Nine canonical payloads paired with their collected evidence index."""

    payloads: Mapping[str, str]
    evidence: GlobalEvidenceIndex


def build_global_payloads(
    output_root: str | Path,
    state: BatchState,
    cache_text: str,
    diagnostics_text: str,
) -> GlobalPayloadBundle:
    """Collect verified maps and render every global compatibility payload."""
    evidence = collect_global_evidence(output_root, state)
    state_text = format_batch_state_json(state)
    if parse_batch_state_json(state_text) != state:
        raise GlobalPublicationError("batch state does not round-trip strictly")
    payloads = {
        "批量提取汇总.tsv": format_batch_summary_tsv(state),
        "批量提取状态.json": state_text,
        "失败与重试.tsv": format_retry_tsv(state),
        "可信描述缓存.tsv": cache_text,
        "批量诊断.jsonl": diagnostics_text,
        "图标缺口汇总.tsv": format_global_icon_gaps_tsv(evidence),
        "图标候选绑定.tsv": format_icon_candidates_tsv(evidence),
        "图标缺口统计.txt": format_icon_gap_statistics(evidence, state),
        "三轴状态汇总.tsv": format_axis_status_tsv(state),
    }
    return GlobalPayloadBundle(MappingProxyType(payloads), evidence)


__all__ = ("GlobalPayloadBundle", "build_global_payloads")
