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


@dataclass(frozen=True, slots=True)
class BatchSemanticEvidence:
    """Persisted evidence needed to re-derive every schema-five axis."""

    publication: PublicationResult
    archive: ArchiveIntegrity
    knowledge: KnowledgeEvidence
    knowledge_reasons: tuple[KnowledgeGapReason, ...]
    state: MapBatchState
    raw_blocks: int
    damaged_blocks: int
    restricted_blocks: int
    valid_icon_references: int
    resolved_icon_references: int
    unresolved_icon_references: int
    unresolved_icons: int
    anonymous_read_failures: int
    original_write_failures: int
    png_failures: int
    icon_failures: int
    current_source_unavailable_count: int
    current_source_conflict_count: int
    relation_partial_count: int
    unresolved_endpoint_count: int
    client_unavailable_icon_count: int


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
    knowledge = KnowledgeEvidence.PARTIAL if reasons else KnowledgeEvidence.COMPLETE
    return BatchAxes(publication, archive, knowledge, reasons)


def batch_semantics_error(evidence: BatchSemanticEvidence) -> str | None:
    """Return a stable contradiction detail, or None for exact derived axes."""
    if evidence.valid_icon_references != (
        evidence.resolved_icon_references + evidence.unresolved_icon_references
    ):
        return (
            "valid icon reference count must equal resolved plus unresolved references"
        )
    if evidence.icon_failures != (
        evidence.anonymous_read_failures
        + evidence.original_write_failures
        + evidence.png_failures
    ):
        return "icon failure count must equal anonymous read plus original write plus PNG failures"
    expected = derive_batch_axes(
        evidence.publication,
        raw_blocks=evidence.raw_blocks,
        damaged_blocks=evidence.damaged_blocks,
        restricted_blocks=evidence.restricted_blocks,
        icon_gaps=evidence.unresolved_icons,
        current_text_states=_current_text_states(evidence),
        relation_partial_count=evidence.relation_partial_count,
        unresolved_endpoint_count=evidence.unresolved_endpoint_count,
        icon_diagnostics=_icon_diagnostics(evidence),
    )
    if evidence.archive is not expected.archive:
        return "archive integrity disagrees with block counters"
    if evidence.knowledge_reasons != expected.knowledge_reasons:
        return "knowledge gap reasons disagree with persisted evidence"
    if evidence.knowledge is not expected.knowledge:
        return "knowledge evidence disagrees with persisted evidence"
    if evidence.state is not derive_legacy_map_state(expected):
        return "legacy state disagrees with authoritative axes"
    return None


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


def _current_text_states(
    evidence: BatchSemanticEvidence,
) -> tuple[ObjectTextState, ...]:
    """Rebuild only persisted current text evidence relevant to status."""
    unavailable = (
        (ObjectTextState.SOURCE_UNAVAILABLE,)
        if evidence.current_source_unavailable_count > 0
        else ()
    )
    conflict = (
        (ObjectTextState.SOURCE_CONFLICT,)
        if evidence.current_source_conflict_count > 0
        else ()
    )
    return unavailable + conflict


def _icon_diagnostics(
    evidence: BatchSemanticEvidence,
) -> tuple[IconDiagnosticFlag, ...]:
    """Rebuild the persisted client-source availability diagnostic."""
    if evidence.client_unavailable_icon_count > 0:
        return (IconDiagnosticFlag.CLIENT_NOT_PROVIDED,)
    return ()


__all__ = (
    "ArchiveIntegrity",
    "BatchAxes",
    "BatchSemanticEvidence",
    "KnowledgeEvidence",
    "KnowledgeGapReason",
    "MapBatchState",
    "PublicationResult",
    "batch_semantics_error",
    "derive_batch_axes",
    "derive_legacy_map_state",
)
