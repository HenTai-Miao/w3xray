"""Trusted description cache setup for resumable batch extraction."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

import w3xtool.batch_runner as batch_runner
from w3xtool.batch_description_cache import build_and_publish_description_cache
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


def test_batch_preserves_published_cache_when_client_rows_are_no_longer_present(
    tmp_path: Path,
) -> None:
    # Given: the first run publishes trusted entries from owned client-fill rows.
    output = tmp_path / "output"
    _write_owned_client_fill(output)
    first = build_and_publish_description_cache(str(output))
    report = output / "地图" / "legacy" / "对象描述.tsv"
    marker = report.parent / ".w3xray-batch-owned"
    report.unlink()
    marker.unlink()
    report.parent.rmdir()
    report.parent.parent.rmdir()

    # When: a later run has no remaining client-fill report to rediscover.
    second = build_and_publish_description_cache(str(output))

    # Then: the validated standalone cache remains available and republished.
    assert len(first.entries) == len(second.entries) == 2
    assert second.lookup("物品", "ratf", "扩展提示", None)[0].raw_value == "完整说明"


def test_batch_removes_previous_value_when_current_owned_reports_conflict(
    tmp_path: Path,
) -> None:
    # Given: a published value is followed by two current owned reports that disagree.
    output = tmp_path / "output"
    _write_owned_client_fill(output)
    build_and_publish_description_cache(str(output))
    _write_owned_client_fill(
        output,
        directory="conflict",
        digest="b" * 64,
        description="冲突说明",
    )

    # When: all historical and current candidates are rebuilt together.
    cache = build_and_publish_description_cache(str(output))

    # Then: the exact key is removed instead of retaining the stale published value.
    assert cache.lookup("物品", "ratf", "扩展提示", None) == ()
    assert cache.conflict_count == 1


def _write_owned_client_fill(
    output: Path,
    *,
    directory: str = "legacy",
    digest: str = "a" * 64,
    description: str = "完整说明",
) -> None:
    report = output / "地图" / directory / "对象描述.tsv"
    report.parent.mkdir(parents=True)
    (report.parent / ".w3xray-batch-owned").write_text(digest, encoding="ascii")
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
                description,
                description,
                "base:ratf",
                "客户端补全",
            )
        )
