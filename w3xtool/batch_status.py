"""Independent publication, archive-integrity, and knowledge-evidence axes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import assert_never

from .icon_evidence_models import IconDiagnosticFlag
from .object_text_models import ObjectTextState

class PublicationResult(StrEnum):
    """Whether one map produced an authoritative publication."""

    PUBLISHED = "已发布"
    FAILED = "失败"
    CANCELLED = "取消"


class MapBatchState(StrEnum):
    """One-schema compatibility projection of the three authoritative axes."""

    COMPLETE = "完整"
    PARTIAL = "部分完成"
    RESTRICTED = "受限"
    FAILED = "失败"
    CANCELLED = "已取消"


class ArchiveIntegrity(StrEnum):
    """Static archive-block evidence independent of publication status."""

    COMPLETE = "完整"
    RAW_BLOCKS = "存在原始块"
    DAMAGED_BLOCKS = "存在损坏块"
    RESTRICTED_BLOCKS = "存在受限块"


class KnowledgeEvidence(StrEnum):
    """Whether all requested knowledge has complete static evidence."""

    COMPLETE = "完整"
    PARTIAL = "部分"


class KnowledgeGapReason(StrEnum):
    """Closed reasons for partial knowledge evidence, in report order."""

    CLIENT_MISSING = "缺少客户端"
    ICON_UNBOUND = "图标未绑定"
    RELATION_PARTIAL = "关系部分"
    TRUE_SOURCE_CONFLICT = "真正来源冲突"
    ENDPOINT_UNRESOLVED = "端点未解析"


@dataclass(frozen=True, slots=True)
class BatchAxes:
    """Three independent status axes plus ordered knowledge reasons."""

    publication: PublicationResult
    archive: ArchiveIntegrity
    knowledge: KnowledgeEvidence
    knowledge_reasons: tuple[KnowledgeGapReason, ...]


def derive_batch_axes(
    publication: PublicationResult,
    *,
    raw_blocks: int,
    damaged_blocks: int,
    restricted_blocks: int,
    icon_gaps: int,
    current_text_states: tuple[ObjectTextState, ...],
    relation_partial_count: int,
    unresolved_endpoint_count: int,
    icon_diagnostics: tuple[IconDiagnosticFlag, ...] = (),
) -> BatchAxes:
    """Derive independent axes from exact counters and current evidence only."""
    archive = _derive_archive_integrity(
        raw_blocks,
        damaged_blocks,
        restricted_blocks,
    )
    reasons = _derive_knowledge_reasons(
        icon_gaps,
        icon_diagnostics,
        current_text_states,
        relation_partial_count,
        unresolved_endpoint_count,
    )
    knowledge = (
        KnowledgeEvidence.PARTIAL if reasons else KnowledgeEvidence.COMPLETE
    )
    return BatchAxes(publication, archive, knowledge, reasons)


def derive_legacy_map_state(axes: BatchAxes) -> MapBatchState:
    """Derive the one-schema compatibility state from authoritative axes."""
    match axes.publication:
        case PublicationResult.FAILED:
            return MapBatchState.FAILED
        case PublicationResult.CANCELLED:
            return MapBatchState.CANCELLED
        case PublicationResult.PUBLISHED:
            pass
        case unreachable:
            assert_never(unreachable)
    match axes.archive:
        case ArchiveIntegrity.RESTRICTED_BLOCKS:
            return MapBatchState.RESTRICTED
        case ArchiveIntegrity.RAW_BLOCKS | ArchiveIntegrity.DAMAGED_BLOCKS:
            return MapBatchState.PARTIAL
        case ArchiveIntegrity.COMPLETE:
            pass
        case unreachable:
            assert_never(unreachable)
    match axes.knowledge:
        case KnowledgeEvidence.PARTIAL:
            return MapBatchState.PARTIAL
        case KnowledgeEvidence.COMPLETE:
            return MapBatchState.COMPLETE
        case unreachable:
            assert_never(unreachable)


def _derive_archive_integrity(
    raw_blocks: int,
    damaged_blocks: int,
    restricted_blocks: int,
) -> ArchiveIntegrity:
    if damaged_blocks > 0:
        return ArchiveIntegrity.DAMAGED_BLOCKS
    if restricted_blocks > 0:
        return ArchiveIntegrity.RESTRICTED_BLOCKS
    if raw_blocks > 0:
        return ArchiveIntegrity.RAW_BLOCKS
    return ArchiveIntegrity.COMPLETE


def _derive_knowledge_reasons(
    icon_gaps: int,
    icon_diagnostics: tuple[IconDiagnosticFlag, ...],
    current_text_states: tuple[ObjectTextState, ...],
    relation_partial_count: int,
    unresolved_endpoint_count: int,
) -> tuple[KnowledgeGapReason, ...]:
    reasons: list[KnowledgeGapReason] = []
    if (
        ObjectTextState.SOURCE_UNAVAILABLE in current_text_states
        or IconDiagnosticFlag.CLIENT_NOT_PROVIDED in icon_diagnostics
    ):
        reasons.append(KnowledgeGapReason.CLIENT_MISSING)
    if icon_gaps > 0:
        reasons.append(KnowledgeGapReason.ICON_UNBOUND)
    if relation_partial_count > 0:
        reasons.append(KnowledgeGapReason.RELATION_PARTIAL)
    if ObjectTextState.SOURCE_CONFLICT in current_text_states:
        reasons.append(KnowledgeGapReason.TRUE_SOURCE_CONFLICT)
    if unresolved_endpoint_count > 0:
        reasons.append(KnowledgeGapReason.ENDPOINT_UNRESOLVED)
    return tuple(reasons)


__all__ = (
    "ArchiveIntegrity",
    "BatchAxes",
    "KnowledgeEvidence",
    "KnowledgeGapReason",
    "MapBatchState",
    "PublicationResult",
    "derive_batch_axes",
    "derive_legacy_map_state",
)
