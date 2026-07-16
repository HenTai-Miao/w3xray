"""Trusted description cache setup for resumable batch extraction."""

from __future__ import annotations

import csv
from pathlib import Path
import shutil

import pytest

from tests.batch_publication_fixture import (
    publish_client_fill_result,
    publish_empty_result,
)
import w3xtool.batch_runner as batch_runner
from w3xtool.batch_description_cache import build_and_publish_description_cache
from w3xtool.description_cache import load_description_cache
from w3xtool.map_data import GameObject
from w3xtool.batch_models import (
    BATCH_SCHEMA_VERSION,
    MapBatchResult,
    SourceFingerprint,
)
from w3xtool.batch_runner import BatchOptions, run_batch
from w3xtool.batch_resume import load_previous_state
from w3xtool.load_context import MapLoadContext
from w3xtool.object_text_index import build_object_text_index
from w3xtool.object_text_models import ObjectTextState


def test_schema_one_root_state_is_not_reused(tmp_path: Path) -> None:
    # Given
    (tmp_path / "批量提取状态.json").write_text(
        '{"schema_version": 1, "results": []}\n',
        encoding="utf-8",
    )

    # When
    previous = load_previous_state(str(tmp_path))

    # Then
    assert previous.state is None
    assert tuple(item.code for item in previous.diagnostics) == (
        "legacy_state_ignored",
    )


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
        return publish_empty_result(
            1,
            fingerprint,
            _options.output_root,
        )

    monkeypatch.setattr(batch_runner, "process_one_map", process)

    # When
    state = run_batch(BatchOptions(str(source_root), str(output)))

    # Then
    assert state.schema_version == BATCH_SCHEMA_VERSION == 4
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


def test_batch_cache_rejects_noncanonical_semantic_siblings(tmp_path: Path) -> None:
    # Given: a valid unit publication contains only long revive and awaken fields.
    output = tmp_path / "output"
    _ = publish_client_fill_result(
        1,
        SourceFingerprint("/maps/old.w3x", 3, 4, "a" * 64),
        str(output),
        values=(
            ("复活提示", "reviveubertip", "复活长提示"),
            ("唤醒提示", "awakenubertip", "唤醒长提示"),
        ),
        category="单位",
        base_id="Hpal",
        object_name="圣骑士",
    )

    # When: the role-only cache is built, published, loaded, and used for fallback.
    _ = build_and_publish_description_cache(str(output))
    loaded = load_description_cache(str(output / "可信描述缓存.tsv"))
    obj = GameObject("单位", "w3u", "H001", "Hpal", "自定义英雄", True)
    index = build_object_text_index(
        (obj,),
        (),
        (),
        loaded,
        client_text_available=True,
    )

    # Then: neither sibling enters the cache or backfills its canonical short field.
    assert loaded.entries == ()
    canonical = tuple(
        row for row in index.records if row.semantic_field in {"revivetip", "awakentip"}
    )
    assert {row.semantic_field for row in canonical} == {"revivetip", "awakentip"}
    assert all(row.state is ObjectTextState.AUTHOR_UNDEFINED for row in canonical)
    assert all(not row.is_current for row in canonical)


def test_batch_cache_keeps_canonical_rows_beside_semantic_siblings(
    tmp_path: Path,
) -> None:
    # Given: canonical, sibling, and existing canonical fields coexist in one report.
    output = tmp_path / "output"
    _ = publish_client_fill_result(
        1,
        SourceFingerprint("/maps/old.w3x", 3, 4, "a" * 64),
        str(output),
        values=(
            ("复活提示", "revivetip", "复活短提示"),
            ("复活提示", "reviveubertip", "复活长提示"),
            ("唤醒提示", "awakentip", "唤醒短提示"),
            ("唤醒提示", "awakenubertip", "唤醒长提示"),
            ("基础提示", "tip", "现有基础提示"),
        ),
        category="单位",
        base_id="Hpal",
        object_name="圣骑士",
    )

    # When: the batch cache is built and round-tripped through its standalone file.
    built = build_and_publish_description_cache(str(output))
    loaded = load_description_cache(str(output / "可信描述缓存.tsv"))

    # Then: siblings cannot conflict away the three safely representable rows.
    expected = {
        "基础提示": "现有基础提示",
        "复活提示": "复活短提示",
        "唤醒提示": "唤醒短提示",
    }
    assert {entry.role: entry.raw_value for entry in built.entries} == expected
    assert {entry.role: entry.raw_value for entry in loaded.entries} == expected
    assert built.conflict_count == loaded.conflict_count == 0
