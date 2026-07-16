"""Two-map conflict fixture for historical description migration."""

from __future__ import annotations

import json
from pathlib import Path

from tests.description_cache_migration_fixture import candidate, legacy_client_fill
from w3xtool.batch_tsv import format_tsv_rows
from w3xtool.description_cache_schema import (
    LEGACY_CACHE_HEADER,
    LEGACY_DESCRIPTION_HEADER,
)

type JsonValue = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)


def write_conflicting_inputs(root: Path) -> tuple[Path, Path]:
    """Write two independently proven maps that disagree on one cache key."""
    legacy_output = root / "legacy-output"
    first_relative = "地图/001_first_aaaaaaaa"
    second_relative = "地图/002_second_bbbbbbbb"
    first_digest = "a" * 64
    second_digest = "b" * 64
    first_report = _write_report(legacy_output, first_relative, "甲")
    second_report = _write_report(legacy_output, second_relative, "乙")
    state = {
        "schema_version": 1,
        "results": [
            _state_result(first_digest, first_relative, "/maps/first.w3x"),
            _state_result(second_digest, second_relative, "/maps/second.w3x"),
        ],
    }
    (legacy_output / "批量提取状态.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    cache_rows = (
        (
            *candidate(raw="甲", source_digest=first_digest)[:7],
            f"{first_report}#base:ratf",
        ),
        (
            *candidate(raw="乙", source_digest=second_digest)[:7],
            f"{second_report}#base:ratf",
        ),
    )
    legacy_cache = root / "legacy-cache.tsv"
    legacy_cache.write_text(
        format_tsv_rows((LEGACY_CACHE_HEADER, *cache_rows)),
        encoding="utf-8",
        newline="",
    )
    return legacy_output, legacy_cache


def _write_report(root: Path, relative: str, raw: str) -> Path:
    directory = root / relative
    directory.mkdir(parents=True)
    report = directory / "对象描述.tsv"
    row = legacy_client_fill(
        raw_description=raw,
        readable_description=raw,
    )
    report.write_text(
        format_tsv_rows((LEGACY_DESCRIPTION_HEADER, row)),
        encoding="utf-8",
        newline="",
    )
    return report


def _state_result(digest: str, relative: str, path: str) -> JsonValue:
    return {
        "source": {"path": path, "size": 3, "mtime_ns": 4, "sha256": digest},
        "display_name": Path(path).stem,
        "output_directory": relative,
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
