"""Exact schema-1/schema-2 fixtures for trusted cache migration tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, assert_never

from w3xtool.batch_tsv import format_tsv_rows
from w3xtool.description_cache_schema import (
    LEGACY_CACHE_HEADER,
    LEGACY_DESCRIPTION_HEADER,
)
from w3xtool.object_text_evidence import readable_text


SOURCE_DIGEST = "a" * 64
LEGACY_RELATIVE = "地图/001_fixture_aaaaaaaa"
type CandidateMutation = Literal[
    "custom_object", "source_digest", "source_label", "readable", "report_value"
]


def candidate(
    *,
    base_id: str = "ratf",
    role: str = "扩展提示",
    raw: str = "原版说明",
    category: str = "物品",
    level: str = "",
    source_digest: str = SOURCE_DIGEST,
    readable: str | None = None,
) -> tuple[str, ...]:
    """Build one exact schema-2 candidate before its source path is known."""
    return (
        category,
        base_id,
        role,
        level,
        raw,
        readable_text(raw) if readable is None else readable,
        source_digest,
        "",
    )


def legacy_client_fill(
    *,
    object_id: str = "ratf",
    base_id: str = "ratf",
    raw_description: str = "原版说明",
    readable_description: str = "原版说明",
    description_source: str = "base:ratf",
    category: str = "物品",
    custom: bool = False,
    level: str = "",
) -> tuple[str, ...]:
    """Build one exact historical client-fill report row."""
    return (
        category,
        object_id,
        base_id,
        "测试对象",
        "是" if custom else "否",
        level,
        "",
        "",
        "",
        raw_description,
        readable_description,
        description_source,
        "客户端补全",
    )


def write_legacy_inputs(
    root: Path,
    *,
    cache_rows: tuple[tuple[str, ...], ...] | None = None,
    report_rows: tuple[tuple[str, ...], ...] | None = None,
    source_paths: tuple[str, ...] | None = None,
) -> tuple[Path, Path]:
    """Write exact legacy state, candidate cache, and source report files."""
    root.mkdir(parents=True, exist_ok=True)
    candidates = cache_rows or (candidate(),)
    reports = report_rows or (legacy_client_fill(),)
    legacy_output = root / "legacy-output"
    map_output = legacy_output / LEGACY_RELATIVE
    map_output.mkdir(parents=True)
    report = map_output / "对象描述.tsv"
    report.write_text(
        format_tsv_rows((LEGACY_DESCRIPTION_HEADER, *reports)),
        encoding="utf-8",
        newline="",
    )
    state = {
        "schema_version": 1,
        "results": [
            {
                "source": {
                    "path": "/maps/source.w3x",
                    "size": 3,
                    "mtime_ns": 4,
                    "sha256": SOURCE_DIGEST,
                },
                "display_name": "source",
                "output_directory": LEGACY_RELATIVE,
                "stage": "published",
                "state": "部分完成",
                "first_error": "",
                "object_count": 1,
                "description_counts": [["客户端补全", 1]],
                "named_icon_count": 0,
                "anonymous_icon_count": 0,
                "original_written_count": 0,
                "png_written_count": 0,
                "icon_failure_count": 0,
                "restricted_block_count": 0,
                "elapsed_ms": 1,
            }
        ],
    }
    (legacy_output / "批量提取状态.json").write_text(
        json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    paths = source_paths or tuple(f"{report}#base:{row[1]}" for row in candidates)
    if len(paths) != len(candidates):
        raise AssertionError("source path count must match candidate count")
    completed = tuple(
        (*row[:7], source_path)
        for row, source_path in zip(candidates, paths, strict=True)
    )
    legacy_cache = root / "legacy-cache.tsv"
    legacy_cache.write_text(
        format_tsv_rows((LEGACY_CACHE_HEADER, *completed)),
        encoding="utf-8",
        newline="",
    )
    return legacy_output, legacy_cache


def write_mutated_inputs(
    root: Path,
    mutation: CandidateMutation,
) -> tuple[Path, Path]:
    """Write one structurally valid candidate with one semantic proof gap."""
    cache_row = candidate()
    report_row = legacy_client_fill()
    match mutation:
        case "custom_object":
            cache_row = candidate(base_id="I001", raw="自定义说明")
            report_row = legacy_client_fill(
                object_id="I001",
                base_id="I001",
                raw_description="自定义说明",
                readable_description="自定义说明",
                description_source="base:I001",
                custom=True,
            )
        case "source_digest":
            cache_row = candidate(source_digest="b" * 64)
        case "source_label":
            report_row = legacy_client_fill(description_source="map:ratf")
        case "readable":
            cache_row = candidate(readable="错误可读值")
        case "report_value":
            report_row = legacy_client_fill(
                raw_description="其他说明",
                readable_description="其他说明",
            )
        case unreachable:
            assert_never(unreachable)
    return write_legacy_inputs(
        root,
        cache_rows=(cache_row,),
        report_rows=(report_row,),
    )
