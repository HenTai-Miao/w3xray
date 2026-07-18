"""Schema-five authoritative batch-result wire contracts."""

from __future__ import annotations

import json
from typing import TypedDict

import pytest

from w3xtool.batch_models import (
    BATCH_SCHEMA_VERSION,
    BatchState,
    BatchStateFormatError,
    MapBatchResult,
    MapBatchState,
    SourceFingerprint,
)
from w3xtool.batch_state_io import format_batch_state_json, parse_batch_state_json
from w3xtool.batch_status import (
    ArchiveIntegrity,
    KnowledgeEvidence,
    KnowledgeGapReason,
    PublicationResult,
)


class _ResultPayload(TypedDict, total=False):
    state: str
    knowledge_evidence: str
    knowledge_gap_reasons: list[str]
    damaged_block_count: int


class _StatePayload(TypedDict):
    schema_version: int
    results: list[_ResultPayload]


def test_schema_five_result_round_trips_authoritative_axes() -> None:
    # Given
    result = _published_result()
    state = BatchState(5, (result,))

    # When
    restored = parse_batch_state_json(format_batch_state_json(state))

    # Then
    assert BATCH_SCHEMA_VERSION == 5
    assert restored == state
    assert restored.results[0].publication_result is PublicationResult.PUBLISHED
    assert restored.results[0].knowledge_gap_reasons == (
        KnowledgeGapReason.ICON_UNBOUND,
    )


@pytest.mark.parametrize(
    ("knowledge", "reasons"),
    (
        (KnowledgeEvidence.COMPLETE.value, [KnowledgeGapReason.ICON_UNBOUND.value]),
        (KnowledgeEvidence.PARTIAL.value, []),
    ),
)
def test_parser_rejects_inconsistent_knowledge_axis(
    knowledge: str,
    reasons: list[str],
) -> None:
    # Given
    payload = _state_payload()
    payload["results"][0]["knowledge_evidence"] = knowledge
    payload["results"][0]["knowledge_gap_reasons"] = reasons

    # When / Then
    with pytest.raises(BatchStateFormatError, match="knowledge"):
        parse_batch_state_json(json.dumps(payload))


def test_parser_rejects_legacy_state_that_disagrees_with_axes() -> None:
    # Given
    payload = _state_payload()
    payload["results"][0]["state"] = MapBatchState.COMPLETE.value

    # When / Then
    with pytest.raises(BatchStateFormatError, match="state|axes"):
        parse_batch_state_json(json.dumps(payload))


def test_parser_rejects_archive_axis_that_disagrees_with_block_counters() -> None:
    # Given
    payload = _state_payload()
    payload["results"][0]["damaged_block_count"] = 1

    # When / Then
    with pytest.raises(BatchStateFormatError, match="archive"):
        parse_batch_state_json(json.dumps(payload))


def test_parser_rejects_icon_gap_claimed_as_complete_knowledge() -> None:
    # Given: the unresolved icon counter proves an icon knowledge gap.
    payload = _state_payload()
    payload["results"][0]["knowledge_evidence"] = KnowledgeEvidence.COMPLETE.value
    payload["results"][0]["knowledge_gap_reasons"] = []
    payload["results"][0]["state"] = MapBatchState.COMPLETE.value

    # When / Then: persisted knowledge must be re-derived from its evidence.
    with pytest.raises(
        BatchStateFormatError, match="knowledge.*reason|reason.*knowledge"
    ):
        parse_batch_state_json(json.dumps(payload))


def _state_payload() -> _StatePayload:
    state = BatchState(BATCH_SCHEMA_VERSION, (_published_result(),))
    return json.loads(format_batch_state_json(state))


def _published_result() -> MapBatchResult:
    return MapBatchResult(
        source=SourceFingerprint("/maps/a.w3x", 3, 4, "a" * 64),
        display_name="a",
        output_directory="地图/001_a_aaaaaaaa",
        stage="published",
        state=MapBatchState.PARTIAL,
        first_error="",
        object_count=0,
        description_counts=(),
        named_icon_count=0,
        anonymous_icon_count=0,
        original_written_count=0,
        png_written_count=0,
        icon_failure_count=0,
        restricted_block_count=0,
        elapsed_ms=1,
        publication_result=PublicationResult.PUBLISHED,
        archive_integrity=ArchiveIntegrity.COMPLETE,
        knowledge_evidence=KnowledgeEvidence.PARTIAL,
        knowledge_gap_reasons=(KnowledgeGapReason.ICON_UNBOUND,),
        raw_block_count=0,
        damaged_block_count=0,
        valid_icon_reference_count=1,
        resolved_icon_reference_count=0,
        filtered_icon_field_count=0,
        unresolved_icon_count=1,
        unresolved_icon_reference_count=1,
        anonymous_read_failure_count=0,
        original_write_failure_count=0,
        png_failure_count=0,
        dependency_fingerprint="b" * 64,
        manifest_sha256="c" * 64,
        published_bytes=1,
    )
