"""Batch schema-v2 persistence and global summary tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from w3xtool.batch_descriptions import DescriptionState
from w3xtool.batch_models import (
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
    state = BatchState(schema_version=2, results=(_map_result(),))

    # When
    restored = parse_batch_state_json(format_batch_state_json(state))

    # Then
    assert restored == state


def test_batch_state_json_rejects_an_unknown_schema() -> None:
    # Given
    payload = '{"schema_version": 1, "results": []}'

    # When / Then
    with pytest.raises(BatchStateFormatError, match="schema"):
        parse_batch_state_json(payload)


def test_global_summary_is_sorted_and_includes_relation_counts() -> None:
    # Given
    state = BatchState(
        schema_version=2,
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
    )
