"""Strict schema-six parser for one authoritative map batch result."""

from __future__ import annotations

import re
from typing import Final

from .batch_models import (
    BatchStateFormatError,
    MapBatchResult,
    MapBatchState,
    SourceFingerprint,
)
from .batch_state_validation import validate_result_state
from .batch_status import (
    ArchiveIntegrity,
    KnowledgeEvidence,
    KnowledgeGapReason,
    PublicationResult,
)


_SHA256: Final = re.compile(r"[0-9a-f]{64}")
_SOURCE_KEYS: Final = frozenset(("path", "size", "mtime_ns", "sha256"))
_RESULT_KEYS: Final = frozenset(
    (
        "source",
        "display_name",
        "output_directory",
        "stage",
        "state",
        "first_error",
        "object_count",
        "description_counts",
        "named_icon_count",
        "anonymous_icon_count",
        "original_written_count",
        "png_written_count",
        "icon_failure_count",
        "restricted_block_count",
        "elapsed_ms",
        "publication_result",
        "archive_integrity",
        "knowledge_evidence",
        "knowledge_gap_reasons",
        "raw_block_count",
        "damaged_block_count",
        "relation_counts",
        "relation_incomplete_count",
        "dependency_fingerprint",
        "manifest_sha256",
        "published_bytes",
        "peak_rss_bytes",
        "valid_icon_reference_count",
        "resolved_icon_reference_count",
        "filtered_icon_field_count",
        "unresolved_icon_count",
        "unresolved_icon_reference_count",
        "anonymous_read_failure_count",
        "original_write_failure_count",
        "png_failure_count",
        "current_source_unavailable_count",
        "current_source_conflict_count",
        "relation_partial_count",
        "unresolved_endpoint_count",
        "client_unavailable_icon_count",
        "source_coverage_gap_count",
    )
)

type JsonValue = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)


def parse_map_batch_result(value: JsonValue) -> MapBatchResult:
    """Parse exact keys, closed enums, counters, and result semantics."""
    raw = _mapping(value, "result")
    _require_keys(raw, _RESULT_KEYS)
    result = MapBatchResult(
        source=_parse_source(raw["source"]),
        display_name=_text(raw["display_name"], "display name"),
        output_directory=_text(raw["output_directory"], "output directory"),
        stage=_text(raw["stage"], "stage"),
        state=_state(raw["state"]),
        first_error=_text(raw["first_error"], "first error"),
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
        elapsed_ms=_nonnegative(raw["elapsed_ms"], "elapsed milliseconds"),
        publication_result=_publication(raw["publication_result"]),
        archive_integrity=_archive(raw["archive_integrity"]),
        knowledge_evidence=_knowledge(raw["knowledge_evidence"]),
        knowledge_gap_reasons=_knowledge_reasons(raw["knowledge_gap_reasons"]),
        raw_block_count=_nonnegative(raw["raw_block_count"], "raw block count"),
        damaged_block_count=_nonnegative(
            raw["damaged_block_count"], "damaged block count"
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
        relation_counts=_counts(raw["relation_counts"], "relation counts"),
        relation_incomplete_count=_nonnegative(
            raw["relation_incomplete_count"], "relation incomplete count"
        ),
        dependency_fingerprint=_text(
            raw["dependency_fingerprint"], "dependency fingerprint"
        ),
        manifest_sha256=_text(raw["manifest_sha256"], "manifest SHA-256"),
        published_bytes=_nonnegative(raw["published_bytes"], "published bytes"),
        peak_rss_bytes=_nonnegative(raw["peak_rss_bytes"], "peak RSS bytes"),
    )
    validate_result_state(result)
    return result


def _parse_source(value: JsonValue) -> SourceFingerprint:
    raw = _mapping(value, "source")
    _require_keys(raw, _SOURCE_KEYS)
    path = _text(raw["path"], "source path")
    if not path:
        raise BatchStateFormatError("source path is empty")
    return SourceFingerprint(
        path,
        _nonnegative(raw["size"], "source size"),
        _nonnegative(raw["mtime_ns"], "source mtime"),
        _digest(raw["sha256"], "source SHA-256"),
    )


def _counts(value: JsonValue, label: str) -> tuple[tuple[str, int], ...]:
    if not isinstance(value, list):
        raise BatchStateFormatError(f"{label} must be a list")
    result: list[tuple[str, int]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, list) or len(item) != 2:
            raise BatchStateFormatError(f"invalid {label} row")
        name = _text(item[0], f"{label} label")
        if not name or name in seen:
            raise BatchStateFormatError(f"duplicate {label} label")
        seen.add(name)
        result.append((name, _nonnegative(item[1], f"{label} value")))
    return tuple(result)


def _knowledge_reasons(value: JsonValue) -> tuple[KnowledgeGapReason, ...]:
    if not isinstance(value, list):
        raise BatchStateFormatError("knowledge gap reasons must be a list")
    reasons = tuple(_knowledge_reason(item) for item in value)
    expected = tuple(reason for reason in KnowledgeGapReason if reason in reasons)
    if reasons != expected:
        raise BatchStateFormatError("knowledge gap reasons are duplicated or unordered")
    return reasons


def _mapping(value: JsonValue, label: str) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise BatchStateFormatError(f"{label} must be an object")
    return value


def _require_keys(value: dict[str, JsonValue], expected: frozenset[str]) -> None:
    if set(value) != expected:
        raise BatchStateFormatError("unexpected batch state keys")


def _text(value: JsonValue, label: str) -> str:
    if not isinstance(value, str):
        raise BatchStateFormatError(f"{label} must be text")
    return value


def _integer(value: JsonValue, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BatchStateFormatError(f"{label} must be an integer")
    return value


def _nonnegative(value: JsonValue, label: str) -> int:
    number = _integer(value, label)
    if number < 0:
        raise BatchStateFormatError(f"{label} must be nonnegative")
    return number


def _digest(value: JsonValue, label: str) -> str:
    digest = _text(value, label)
    if _SHA256.fullmatch(digest) is None:
        raise BatchStateFormatError(f"invalid {label}")
    return digest


def _state(value: JsonValue) -> MapBatchState:
    try:
        return MapBatchState(_text(value, "map state"))
    except ValueError as exc:
        raise BatchStateFormatError("invalid map state") from exc


def _publication(value: JsonValue) -> PublicationResult:
    try:
        return PublicationResult(_text(value, "publication result"))
    except ValueError as exc:
        raise BatchStateFormatError("invalid publication result") from exc


def _archive(value: JsonValue) -> ArchiveIntegrity:
    try:
        return ArchiveIntegrity(_text(value, "archive integrity"))
    except ValueError as exc:
        raise BatchStateFormatError("invalid archive integrity") from exc


def _knowledge(value: JsonValue) -> KnowledgeEvidence:
    try:
        return KnowledgeEvidence(_text(value, "knowledge evidence"))
    except ValueError as exc:
        raise BatchStateFormatError("invalid knowledge evidence") from exc


def _knowledge_reason(value: JsonValue) -> KnowledgeGapReason:
    try:
        return KnowledgeGapReason(_text(value, "knowledge gap reason"))
    except ValueError as exc:
        raise BatchStateFormatError("invalid knowledge gap reason") from exc


__all__ = ("JsonValue", "parse_map_batch_result")
