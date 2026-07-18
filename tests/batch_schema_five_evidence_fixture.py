"""Reports whose aggregate counters agree but schema-five evidence disagrees."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, assert_never

from dataclasses import replace
from w3xtool.batch_reports import format_icon_index_tsv
from w3xtool.batch_tsv import format_tsv_rows
from w3xtool.batch_models import MapBatchResult
from w3xtool.batch_status import (
    PublicationResult,
    derive_batch_axes,
    derive_legacy_map_state,
)
from w3xtool.icon_evidence_exports import (
    format_icon_integrity,
    format_unresolved_icon_tsv,
)
from w3xtool.icon_evidence_index import IconEvidenceIndex
from w3xtool.icon_evidence_models import (
    IconDiagnosticFlag,
    IconGapReason,
    UnresolvedIconEvidence,
)
from w3xtool.icon_resources import IconObjectReference
from w3xtool.item_relation_exports import ACQUISITION_REPORT_HEADER
from w3xtool.item_relation_models import ItemRelationKind, RelationCompleteness
from w3xtool.object_text_exports import OBJECT_TEXT_REPORT_HEADER
from w3xtool.object_text_models import ObjectTextState


type EvidenceKind = Literal["current_text", "relation", "icon_diagnostic"]


def write_schema_five_evidence_reports(root: Path, kind: EvidenceKind) -> None:
    """Leave aggregate reports valid while changing one precise evidence dimension."""
    match kind:
        case "current_text":
            _write_noncurrent_unavailable_text(root)
        case "relation":
            _write_unresolved_relation(root)
        case "icon_diagnostic":
            _write_undiagnosed_icon_gap(root)
        case unreachable:
            assert_never(unreachable)


def schema_five_evidence_result(
    result: MapBatchResult,
    kind: EvidenceKind,
) -> MapBatchResult:
    """Produce a semantically valid summary for one report-evidence drift case."""
    match kind:
        case "current_text":
            axes = derive_batch_axes(
                PublicationResult.PUBLISHED,
                raw_blocks=0,
                damaged_blocks=0,
                restricted_blocks=0,
                icon_gaps=0,
                current_text_states=(ObjectTextState.SOURCE_UNAVAILABLE,),
                relation_partial_count=0,
                unresolved_endpoint_count=0,
            )
            return replace(
                result,
                state=derive_legacy_map_state(axes),
                knowledge_evidence=axes.knowledge,
                knowledge_gap_reasons=axes.knowledge_reasons,
                description_counts=tuple(
                    (state.value, int(state is ObjectTextState.SOURCE_UNAVAILABLE))
                    for state in ObjectTextState
                ),
                current_source_unavailable_count=1,
            )
        case "relation":
            axes = derive_batch_axes(
                PublicationResult.PUBLISHED,
                raw_blocks=0,
                damaged_blocks=0,
                restricted_blocks=0,
                icon_gaps=0,
                current_text_states=(),
                relation_partial_count=1,
                unresolved_endpoint_count=0,
            )
            return replace(
                result,
                state=derive_legacy_map_state(axes),
                knowledge_evidence=axes.knowledge,
                knowledge_gap_reasons=axes.knowledge_reasons,
                relation_counts=(("怪物直接掉落", 1),),
                relation_incomplete_count=1,
                relation_partial_count=1,
            )
        case "icon_diagnostic":
            axes = derive_batch_axes(
                PublicationResult.PUBLISHED,
                raw_blocks=0,
                damaged_blocks=0,
                restricted_blocks=0,
                icon_gaps=1,
                current_text_states=(),
                relation_partial_count=0,
                unresolved_endpoint_count=0,
                icon_diagnostics=(IconDiagnosticFlag.CLIENT_NOT_PROVIDED,),
            )
            return replace(
                result,
                state=derive_legacy_map_state(axes),
                knowledge_evidence=axes.knowledge,
                knowledge_gap_reasons=axes.knowledge_reasons,
                valid_icon_reference_count=1,
                unresolved_icon_count=1,
                unresolved_icon_reference_count=1,
                client_unavailable_icon_count=1,
            )
        case unreachable:
            assert_never(unreachable)


def _write_noncurrent_unavailable_text(root: Path) -> None:
    row = (
        *("" for _ in range(15)),
        ObjectTextState.SOURCE_UNAVAILABLE.value,
        "",
        "",
        "否",
        "",
        "",
    )
    (root / "对象完整描述.tsv").write_text(
        format_tsv_rows((OBJECT_TEXT_REPORT_HEADER, row)),
        encoding="utf-8",
        newline="",
    )


def _write_unresolved_relation(root: Path) -> None:
    row = (
        "",
        "",
        ItemRelationKind.UNIT_DROP.value,
        *("" for _ in range(21)),
        RelationCompleteness.UNRESOLVED.value,
        "",
    )
    (root / "掉落与获取关系.tsv").write_text(
        format_tsv_rows((ACQUISITION_REPORT_HEADER, row)),
        encoding="utf-8",
        newline="",
    )


def _write_undiagnosed_icon_gap(root: Path) -> None:
    index = IconEvidenceIndex.build(
        unresolved=(
            UnresolvedIconEvidence(
                IconObjectReference(
                    "技能",
                    "A001",
                    "暴风雪",
                    "AHbz",
                    "map.w3x",
                    "a" * 64,
                    "map.w3x",
                    "aart",
                    "图标 - 普通",
                    "icon",
                    "war3map.w3a",
                    "",
                    r"Icons\Missing.blp",
                    r"Icons\Missing.blp",
                ),
                IconGapReason.NAMED_RESOURCE_MISSING,
                (),
                (),
            ),
        )
    )
    (root / "图标索引.tsv").write_text(
        format_icon_index_tsv(()), encoding="utf-8", newline=""
    )
    (root / "图标未解析.tsv").write_text(
        format_unresolved_icon_tsv(index), encoding="utf-8", newline=""
    )
    (root / "图标完整性.txt").write_text(
        format_icon_integrity(index, ()), encoding="utf-8"
    )
