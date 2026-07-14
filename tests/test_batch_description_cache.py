"""Trusted description cache setup for resumable batch extraction."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

import w3xtool.batch_runner as batch_runner
from w3xtool.batch_models import MapBatchResult, MapBatchState, SourceFingerprint
from w3xtool.batch_runner import BatchOptions, run_batch
from w3xtool.load_context import MapLoadContext


_LEGACY_HEADER = (
    "分类",
    "对象ID",
    "基础ID",
    "名称",
    "自定义",
    "等级",
    "原始提示",
    "可读提示",
    "提示来源",
    "原始说明",
    "可读说明",
    "说明来源",
    "完整性状态",
)


def test_schema_one_state_is_not_reused_after_v2_reports_are_required(
    tmp_path: Path,
) -> None:
    # Given
    (tmp_path / "批量提取状态.json").write_text(
        '{"schema_version": 1, "results": []}\n', encoding="utf-8"
    )

    # When
    previous = batch_runner._read_previous_state(str(tmp_path))

    # Then
    assert previous is None


def test_batch_builds_and_publishes_cache_before_processing_maps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    source_root = tmp_path / "Maps"
    source_root.mkdir()
    (source_root / "sample.w3x").write_bytes(b"map")
    output = tmp_path / "output"
    _write_owned_client_fill(output)
    monkeypatch.setattr(
        batch_runner, "build_map_load_context", lambda **_kwargs: MapLoadContext()
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
    assert state.schema_version == 2
    assert seen_cache_sizes == [2]
    cache_path = output / "可信描述缓存.tsv"
    assert cache_path.is_file()
    with cache_path.open("r", encoding="utf-8", newline="") as handle:
        rows = tuple(csv.reader(handle, delimiter="\t"))
    assert rows[1][4] == "基础提示"
    assert rows[2][4] == "完整说明"


def _write_owned_client_fill(output: Path) -> None:
    report = output / "地图" / "legacy" / "对象描述.tsv"
    report.parent.mkdir(parents=True)
    (report.parent / ".w3xray-batch-owned").write_text("a" * 64, encoding="ascii")
    with report.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(_LEGACY_HEADER)
        writer.writerow(
            (
                "物品",
                "ratf",
                "ratf",
                "戒指",
                "否",
                "",
                "基础提示",
                "基础提示",
                "base:ratf",
                "完整说明",
                "完整说明",
                "base:ratf",
                "客户端补全",
            )
        )
