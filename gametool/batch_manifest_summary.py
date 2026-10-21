"""Strict JSON codec for the report-reconciled manifest result summary."""

from __future__ import annotations

from typing import Final

from .batch_manifest_models import BatchManifestFormatError, ManifestResultSummary
from .batch_manifest_summary_validation import validate_manifest_summary
from .batch_models import MapBatchState
from .batch_status import (
    ArchiveIntegrity,
    KnowledgeEvidence,
    KnowledgeGapReason,
    PublicationResult,
)

type JsonValue = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)

_SUMMARY_KEYS: Final = frozenset(
    (
        "anonymous_icon_count",
        "anonymous_read_failure_count",
        "archive_integrity",
        "damaged_block_count",
        "description_counts",
        "filtered_icon_field_count",
        "icon_failure_count",
        "knowledge_evidence",
        "knowledge_gap_reasons",
        "named_icon_count",
        "object_count",
        "original_write_failure_count",
        "original_written_count",
        "png_failure_count",
        "current_source_unavailable_count",
        "current_source_conflict_count",
        "relation_partial_count",
        "unresolved_endpoint_count",
        "client_unavailable_icon_count",
        "source_coverage_gap_count",
        "png_written_count",
        "publication_result",
        "raw_block_count",
        "relation_counts",
        "relation_incomplete_count",
        "resolved_icon_reference_count",
        "restricted_block_count",
        "stage",
        "state",
        "unresolved_icon_count",
        "unresolved_icon_reference_count",
        "valid_icon_reference_count",
    )
)


def manifest_summary_payload(summary: ManifestResultSummary) -> dict[str, JsonValue]:
    """Return the deterministic JSON-compatible summary mapping."""
    return {
        "anonymous_icon_count": summary.anonymous_icon_count,
        "anonymous_read_failure_count": summary.anonymous_read_failure_count,
        "archive_integrity": summary.archive_integrity.value,
        "damaged_block_count": summary.damaged_block_count,
        "description_counts": [list(item) for item in summary.description_counts],
        "filtered_icon_field_count": summary.filtered_icon_field_count,
        "icon_failure_count": summary.icon_failure_count,
        "knowledge_evidence": summary.knowledge_evidence.value,
        "knowledge_gap_reasons": [
            reason.value for reason in summary.knowledge_gap_reasons
        ],
        "named_icon_count": summary.named_icon_count,
        "object_count": summary.object_count,
        "original_write_failure_count": summary.original_write_failure_count,
        "original_written_count": summary.original_written_count,
        "png_failure_count": summary.png_failure_count,
        "current_source_unavailable_count": summary.current_source_unavailable_count,
        "current_source_conflict_count": summary.current_source_conflict_count,
        "relation_partial_count": summary.relation_partial_count,
        "unresolved_endpoint_count": summary.unresolved_endpoint_count,
        "client_unavailable_icon_count": summary.client_unavailable_icon_count,
        "source_coverage_gap_count": summary.source_coverage_gap_count,
        "png_written_count": summary.png_written_count,
        "publication_result": summary.publication_result.value,
        "raw_block_count": summary.raw_block_count,
        "relation_counts": [list(item) for item in summary.relation_counts],
        "relation_incomplete_count": summary.relation_incomplete_count,
        "resolved_icon_reference_count": summary.resolved_icon_reference_count,
        "restricted_block_count": summary.restricted_block_count,
        "stage": summary.stage,
        "state": summary.state.value,
        "unresolved_icon_count": summary.unresolved_icon_count,
        "unresolved_icon_reference_count": summary.unresolved_icon_reference_count,
        "valid_icon_reference_count": summary.valid_icon_reference_count,
    }


def parse_manifest_summary(value: JsonValue) -> ManifestResultSummary:
    """Parse an exact-key, nonnegative manifest result summary."""
    raw = _mapping(value, "result")
    _require_keys(raw, _SUMMARY_KEYS)
    summary = ManifestResultSummary(
        stage=_string(raw["stage"], "result stage"),
        state=_state(raw["state"]),
        publication_result=_publication(raw["publication_result"]),
        archive_integrity=_archive(raw["archive_integrity"]),
        knowledge_evidence=_knowledge(raw["knowledge_evidence"]),
        knowledge_gap_reasons=_knowledge_reasons(raw["knowledge_gap_reasons"]),
        object_count=_nonnegative(raw["object_count"], "object count"),
        description_counts=_counts(raw["description_counts"], "description counts"),
        named_icon_count=_nonnegative(raw["named_icon_count"], "named icon count"),
        anonymous_icon_count=_nonnegative(
            raw["anonymous_icon_count"], "anonymous icon count"
        ),
        original_written_count=_nonnegative(
            raw["original_written_count"], "original written count"
        ),
        png_written_count=_nonnegative(raw["png_written_count"], "PNG written count"),
        icon_failure_count=_nonnegative(
            raw["icon_failure_count"], "icon failure count"
        ),
        restricted_block_count=_nonnegative(
            raw["restricted_block_count"], "restricted block count"
        ),
        raw_block_count=_nonnegative(raw["raw_block_count"], "raw block count"),
        damaged_block_count=_nonnegative(
            raw["damaged_block_count"], "damaged block count"
        ),
        relation_counts=_counts(raw["relation_counts"], "relation counts"),
        relation_incomplete_count=_nonnegative(
            raw["relation_incomplete_count"], "relation incomplete count"
        ),
        valid_icon_reference_count=_nonnegative(
            raw["valid_icon_reference_count"], "valid icon reference count"
        ),
        resolved_icon_reference_count=_nonnegative(
            raw["resolved_icon_reference_count"], "resolved icon reference count"
        ),
        filtered_icon_field_count=_nonnegative(
            raw["filtered_icon_field_count"], "filtered icon field count"
        ),
        unresolved_icon_count=_nonnegative(
            raw["unresolved_icon_count"], "unresolved icon count"
        ),
        unresolved_icon_reference_count=_nonnegative(
            raw["unresolved_icon_reference_count"],
            "unresolved icon reference count",
        ),
        anonymous_read_failure_count=_nonnegative(
            raw["anonymous_read_failure_count"], "anonymous read failure count"
        ),
        original_write_failure_count=_nonnegative(
            raw["original_write_failure_count"], "original write failure count"
        ),
        png_failure_count=_nonnegative(raw["png_failure_count"], "PNG failure count"),
        current_source_unavailable_count=_nonnegative(
            raw["current_source_unavailable_count"],
            "current source unavailable count",
        ),
        current_source_conflict_count=_nonnegative(
            raw["current_source_conflict_count"],
            "current source conflict count",
        ),
        relation_partial_count=_nonnegative(
            raw["relation_partial_count"], "relation partial count"
        ),
        unresolved_endpoint_count=_nonnegative(
            raw["unresolved_endpoint_count"], "unresolved endpoint count"
        ),
        client_unavailable_icon_count=_nonnegative(
            raw["client_unavailable_icon_count"],
            "client unavailable icon count",
        ),
        source_coverage_gap_count=_nonnegative(
            raw["source_coverage_gap_count"], "source coverage gap count"
        ),
    )
    validate_manifest_summary(summary)
    return summary


def _counts(value: JsonValue, label: str) -> tuple[tuple[str, int], ...]:
    if not isinstance(value, list):
        raise BatchManifestFormatError(f"{label} must be a list")
    result: list[tuple[str, int]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, list) or len(item) != 2:
            raise BatchManifestFormatError(f"invalid {label} row")
        name = _string(item[0], f"{label} label")
        if not name or name in seen:
            raise BatchManifestFormatError(f"duplicate {label} label")
        seen.add(name)
        result.append((name, _nonnegative(item[1], f"{label} value")))
    return tuple(result)


def _knowledge_reasons(value: JsonValue) -> tuple[KnowledgeGapReason, ...]:
    if not isinstance(value, list):
        raise BatchManifestFormatError("knowledge gap reasons must be a list")
    try:
        reasons = tuple(
            KnowledgeGapReason(_string(item, "knowledge gap reason")) for item in value
        )
    except ValueError as exc:
        raise BatchManifestFormatError("invalid knowledge gap reason") from exc
    expected = tuple(reason for reason in KnowledgeGapReason if reason in reasons)
    if reasons != expected:
        raise BatchManifestFormatError(
            "knowledge gap reasons are duplicated or unordered"
        )
    return reasons


def _mapping(value: JsonValue, label: str) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise BatchManifestFormatError(f"{label} must be an object")
    return value


def _require_keys(value: dict[str, JsonValue], expected: frozenset[str]) -> None:
    if set(value) != expected:
        raise BatchManifestFormatError("unexpected JSON keys")


def _string(value: JsonValue, label: str) -> str:
    if not isinstance(value, str):
        raise BatchManifestFormatError(f"{label} must be text")
    return value


def _nonnegative(value: JsonValue, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BatchManifestFormatError(f"{label} must be an integer")
    if value < 0:
        raise BatchManifestFormatError(f"{label} must be nonnegative")
    return value


def _state(value: JsonValue) -> MapBatchState:
    try:
        return MapBatchState(_string(value, "result state"))
    except ValueError as exc:
        raise BatchManifestFormatError("invalid result state") from exc


def _publication(value: JsonValue) -> PublicationResult:
    try:
        return PublicationResult(_string(value, "publication result"))
    except ValueError as exc:
        raise BatchManifestFormatError("invalid publication result") from exc


def _archive(value: JsonValue) -> ArchiveIntegrity:
    try:
        return ArchiveIntegrity(_string(value, "archive integrity"))
    except ValueError as exc:
        raise BatchManifestFormatError("invalid archive integrity") from exc


def _knowledge(value: JsonValue) -> KnowledgeEvidence:
    try:
        return KnowledgeEvidence(_string(value, "knowledge evidence"))
    except ValueError as exc:
        raise BatchManifestFormatError("invalid knowledge evidence") from exc
