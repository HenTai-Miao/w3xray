"""Batch schema-five persistence and global summary tests."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from w3xtool.batch_descriptions import DescriptionState
from w3xtool.batch_models import (
    BATCH_SCHEMA_VERSION,
    BatchState,
    BatchStateFormatError,
    MapBatchResult,
    MapBatchState,
    SourceFingerprint,
)
from w3xtool.batch_reports import (
    format_batch_state_json,
    format_batch_summary_tsv,
    format_retry_tsv,
    parse_batch_state_json,
)
from w3xtool.batch_status import (
    PublicationResult,
    derive_batch_axes,
    derive_legacy_map_state,
)


def test_batch_state_json_round_trips_source_fingerprint() -> None:
    # Given
    state = BatchState(schema_version=BATCH_SCHEMA_VERSION, results=(_map_result(),))

    # When
    restored = parse_batch_state_json(format_batch_state_json(state))

    # Then
    assert restored == state


def test_batch_schema_is_five_for_independent_status_axes() -> None:
    assert BATCH_SCHEMA_VERSION == 5


def test_batch_state_json_rejects_an_unknown_schema() -> None:
    # Given
    payload = '{"schema_version": 1, "results": []}'

    # When / Then
    with pytest.raises(BatchStateFormatError, match="schema"):
        parse_batch_state_json(payload)


def test_global_summary_is_sorted_and_includes_relation_counts() -> None:
    # Given
    state = BatchState(
        schema_version=BATCH_SCHEMA_VERSION,
        results=(
            _map_result(source_path="/maps/z.w3x"),
            _map_result(source_path="/maps/a.w3x"),
        ),
    )

    # When
    lines = format_batch_summary_tsv(state).splitlines()

    # Then
    assert lines[1].startswith("/maps/a.w3x\t")
    assert lines[2].startswith("/maps/z.w3x\t")
    assert "关系类型计数" in lines[0]
    assert "关系不完整" in lines[0]


def test_retry_report_excludes_published_partial_knowledge() -> None:
    # Given
    published = _map_result()
    terminal_axes = derive_batch_axes(
        PublicationResult.FAILED,
        raw_blocks=0,
        damaged_blocks=0,
        restricted_blocks=0,
        icon_gaps=0,
        current_text_states=(),
        relation_partial_count=0,
        unresolved_endpoint_count=0,
    )
    failed = replace(
        published,
        source=SourceFingerprint("/maps/failed.w3x", 3, 4, "f" * 64),
        display_name="failed",
        output_directory="",
        stage="load/process",
        state=derive_legacy_map_state(terminal_axes),
        first_error="broken",
        publication_result=terminal_axes.publication,
        archive_integrity=terminal_axes.archive,
        knowledge_evidence=terminal_axes.knowledge,
        knowledge_gap_reasons=terminal_axes.knowledge_reasons,
        manifest_sha256="",
        published_bytes=0,
    )

    # When
    report = format_retry_tsv(BatchState(BATCH_SCHEMA_VERSION, (published, failed)))

    # Then
    assert "/maps/failed.w3x" in report
    assert published.source.path not in report


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("object_count", -1),
        ("elapsed_ms", -1),
        ("published_bytes", -1),
        ("peak_rss_bytes", -1),
        ("dependency_fingerprint", "BAD"),
        ("manifest_sha256", "A" * 64),
        ("output_directory", "../escape"),
    ),
)
def test_batch_state_parser_rejects_invalid_published_result_fields(
    field: str,
    value: str | int,
) -> None:
    # Given: one formatted result is corrupted at a semantic boundary.
    payload = json.loads(
        format_batch_state_json(BatchState(BATCH_SCHEMA_VERSION, (_map_result(),)))
    )
    payload["results"][0][field] = value

    # When / Then: coercion never turns invalid persisted data into trusted state.
    with pytest.raises(BatchStateFormatError):
        parse_batch_state_json(json.dumps(payload))


def test_batch_state_parser_rejects_duplicate_paths_and_source_identities() -> None:
    # Given: two result rows alias both their path and immutable source identity.
    state = BatchState(BATCH_SCHEMA_VERSION, (_map_result(),))
    payload = json.loads(format_batch_state_json(state))
    duplicate = dict(payload["results"][0])
    duplicate["source"] = dict(duplicate["source"])
    duplicate["source"]["path"] = "/MAPS/A.W3X"
    payload["results"].append(duplicate)

    # When / Then
    with pytest.raises(BatchStateFormatError, match="duplicate"):
        parse_batch_state_json(json.dumps(payload))


def test_batch_state_parser_rejects_duplicate_count_labels_and_extra_keys() -> None:
    # Given
    payload = json.loads(
        format_batch_state_json(BatchState(BATCH_SCHEMA_VERSION, (_map_result(),)))
    )
    payload["results"][0]["description_counts"].append(
        payload["results"][0]["description_counts"][0]
    )
    payload["results"][0]["unexpected"] = True

    # When / Then
    with pytest.raises(BatchStateFormatError):
        parse_batch_state_json(json.dumps(payload))


def test_batch_state_parser_rejects_impossible_failed_publication() -> None:
    # Given
    payload = json.loads(
        format_batch_state_json(BatchState(BATCH_SCHEMA_VERSION, (_map_result(),)))
    )
    payload["results"][0]["state"] = MapBatchState.FAILED.value

    # When / Then
    with pytest.raises(BatchStateFormatError, match="state|stage"):
        parse_batch_state_json(json.dumps(payload))


def test_batch_state_parser_rejects_unreconciled_valid_icon_references() -> None:
    # Given: the aggregate no longer equals its resolved and unresolved parts.
    payload = json.loads(
        format_batch_state_json(BatchState(BATCH_SCHEMA_VERSION, (_map_result(),)))
    )
    payload["results"][0]["valid_icon_reference_count"] = 8

    # When / Then
    with pytest.raises(
        BatchStateFormatError,
        match="valid icon reference count must equal resolved plus unresolved references",
    ):
        parse_batch_state_json(json.dumps(payload))


def test_batch_state_parser_rejects_unreconciled_icon_failures() -> None:
    # Given: the aggregate no longer equals its three physical failure parts.
    payload = json.loads(
        format_batch_state_json(BatchState(BATCH_SCHEMA_VERSION, (_map_result(),)))
    )
    payload["results"][0]["icon_failure_count"] = 7

    # When / Then
    with pytest.raises(
        BatchStateFormatError,
        match="icon failure count must equal anonymous read plus original write plus PNG failures",
    ):
        parse_batch_state_json(json.dumps(payload))


def _map_result(*, source_path: str = "/maps/a.w3x") -> MapBatchResult:
    axes = derive_batch_axes(
        PublicationResult.PUBLISHED,
        raw_blocks=0,
        damaged_blocks=0,
        restricted_blocks=0,
        icon_gaps=2,
        current_text_states=(),
        relation_partial_count=1,
        unresolved_endpoint_count=0,
    )
    return MapBatchResult(
        source=SourceFingerprint(source_path, 100, 123456, "a" * 64),
        display_name=Path(source_path).stem,
        output_directory="地图/001_a_aaaaaaaa",
        stage="published",
        state=derive_legacy_map_state(axes),
        first_error="",
        object_count=1,
        description_counts=((DescriptionState.MAP_VALUE.value, 1),),
        named_icon_count=1,
        anonymous_icon_count=0,
        original_written_count=1,
        png_written_count=1,
        icon_failure_count=6,
        restricted_block_count=0,
        elapsed_ms=25,
        publication_result=axes.publication,
        archive_integrity=axes.archive,
        knowledge_evidence=axes.knowledge,
        knowledge_gap_reasons=axes.knowledge_reasons,
        raw_block_count=0,
        damaged_block_count=0,
        valid_icon_reference_count=7,
        resolved_icon_reference_count=3,
        filtered_icon_field_count=2,
        unresolved_icon_count=2,
        unresolved_icon_reference_count=4,
        anonymous_read_failure_count=1,
        original_write_failure_count=2,
        png_failure_count=3,
        relation_partial_count=1,
        relation_counts=(("怪物直接掉落", 2),),
        relation_incomplete_count=1,
        dependency_fingerprint="b" * 64,
        manifest_sha256="c" * 64,
        published_bytes=100,
        peak_rss_bytes=10,
    )
