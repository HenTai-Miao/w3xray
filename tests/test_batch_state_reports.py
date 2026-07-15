"""Batch schema-4 persistence and global summary tests."""

from __future__ import annotations

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
    parse_batch_state_json,
)


def test_batch_state_json_round_trips_source_fingerprint() -> None:
    # Given
    state = BatchState(schema_version=BATCH_SCHEMA_VERSION, results=(_map_result(),))

    # When
    restored = parse_batch_state_json(format_batch_state_json(state))

    # Then
    assert restored == state


def test_batch_schema_is_four_for_category_safe_relation_state() -> None:
    assert BATCH_SCHEMA_VERSION == 4


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


def _map_result(*, source_path: str = "/maps/a.w3x") -> MapBatchResult:
    return MapBatchResult(
        source=SourceFingerprint(source_path, 100, 123456, "a" * 64),
        display_name=Path(source_path).stem,
        output_directory="地图/001_a_aaaaaaaa",
        stage="published",
        state=MapBatchState.COMPLETE,
        first_error="",
        object_count=1,
        description_counts=((DescriptionState.MAP_VALUE.value, 1),),
        named_icon_count=1,
        anonymous_icon_count=0,
        original_written_count=1,
        png_written_count=1,
        icon_failure_count=0,
        restricted_block_count=0,
        elapsed_ms=25,
        relation_counts=(("怪物直接掉落", 2),),
        relation_incomplete_count=1,
        dependency_fingerprint="b" * 64,
        manifest_sha256="c" * 64,
        published_bytes=100,
        peak_rss_bytes=10,
    )
