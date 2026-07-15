"""Trusted description cache setup for resumable batch extraction."""

from __future__ import annotations

import csv
from pathlib import Path
import shutil

import pytest

from tests.batch_publication_fixture import publish_client_fill_result
import w3xtool.batch_runner as batch_runner
from w3xtool.batch_description_cache import build_and_publish_description_cache
from w3xtool.batch_models import (
    BATCH_SCHEMA_VERSION,
    MapBatchResult,
    MapBatchState,
    SourceFingerprint,
)
from w3xtool.batch_runner import BatchOptions, run_batch
from w3xtool.load_context import MapLoadContext


def test_schema_one_root_state_is_not_reused(tmp_path: Path) -> None:
    # Given
    (tmp_path / "批量提取状态.json").write_text(
        '{"schema_version": 1, "results": []}\n',
        encoding="utf-8",
    )

    # When / Then
    assert batch_runner._read_previous_state(str(tmp_path)) is None


def test_batch_builds_and_publishes_cache_before_processing_maps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: one previously published map has two manifest-bound client rows.
    source_root = tmp_path / "Maps"
    source_root.mkdir()
    (source_root / "sample.w3x").write_bytes(b"map")
    output = tmp_path / "output"
    _ = publish_client_fill_result(
        1,
        SourceFingerprint("/maps/old.w3x", 3, 4, "a" * 64),
        str(output),
        values=(("基础提示", "基础提示"), ("扩展提示", "完整说明")),
    )
    monkeypatch.setattr(
        batch_runner,
        "build_map_load_context",
        lambda **_kwargs: MapLoadContext(),
    )
    seen_cache_sizes: list[int] = []

    def process(
        _index: int,
        fingerprint: SourceFingerprint,
        _options: BatchOptions,
        context: MapLoadContext,
    ) -> MapBatchResult:
        seen_cache_sizes.append(len(context.description_cache.entries))
        return MapBatchResult(
            source=fingerprint,
            display_name="sample",
            output_directory="地图/001_sample",
            stage="published",
            state=MapBatchState.COMPLETE,
            first_error="",
            object_count=0,
            description_counts=(),
            named_icon_count=0,
            anonymous_icon_count=0,
            original_written_count=0,
            png_written_count=0,
            icon_failure_count=0,
            restricted_block_count=0,
            elapsed_ms=0,
        )

    monkeypatch.setattr(batch_runner, "process_one_map", process)

    # When
    state = run_batch(BatchOptions(str(source_root), str(output)))

    # Then
    assert state.schema_version == BATCH_SCHEMA_VERSION == 3
    assert seen_cache_sizes == [2]
    with (output / "可信描述缓存.tsv").open(
        "r",
        encoding="utf-8",
        newline="",
    ) as handle:
        rows = tuple(csv.reader(handle, delimiter="\t"))
    assert rows[1][4] == "基础提示"
    assert rows[2][4] == "完整说明"


def test_unpointed_root_cache_is_not_an_automatic_seed(tmp_path: Path) -> None:
    # Given: a cache mirror exists, but no validated global current pointer does.
    output = tmp_path / "output"
    _ = publish_client_fill_result(
        1,
        SourceFingerprint("/maps/old.w3x", 3, 4, "a" * 64),
        str(output),
    )
    first = build_and_publish_description_cache(str(output))
    shutil.rmtree(output / "地图")

    # When
    second = build_and_publish_description_cache(str(output))

    # Then
    assert len(first.entries) == 1
    assert second.entries == ()


def test_batch_removes_values_when_valid_publications_conflict(
    tmp_path: Path,
) -> None:
    # Given
    output = tmp_path / "output"
    _ = publish_client_fill_result(
        1,
        SourceFingerprint("/maps/a.w3x", 3, 4, "a" * 64),
        str(output),
        values=(("扩展提示", "原说明"),),
    )
    _ = publish_client_fill_result(
        2,
        SourceFingerprint("/maps/b.w3x", 3, 4, "b" * 64),
        str(output),
        values=(("扩展提示", "冲突说明"),),
    )

    # When
    cache = build_and_publish_description_cache(str(output))

    # Then
    assert cache.lookup("物品", "ratf", "扩展提示", None) == ()
    assert cache.conflict_count == 1
