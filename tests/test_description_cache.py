"""Lossless standalone description-cache TSV contracts."""

from __future__ import annotations

import csv
import io
from pathlib import Path

from w3xtool.description_cache import (
    DescriptionCache,
    DescriptionCacheEntry,
    format_description_cache_tsv,
    load_description_cache,
)


def test_formatted_cache_round_trips_all_text_and_both_source_hashes(
    tmp_path: Path,
) -> None:
    # Given: raw text contains a formula, TSV controls, newlines, and edge spaces.
    raw = ' \u200e=HYPERLINK("https://example.invalid")\t正文\r\n第二行  '
    expected = DescriptionCacheEntry(
        "物品",
        "ratf",
        "扩展提示",
        None,
        raw,
        raw,
        "d" * 64,
        "e" * 64,
        "owned.tsv",
    )
    cache = DescriptionCache.build((expected,))
    path = tmp_path / "可信描述缓存.tsv"
    report = format_description_cache_tsv(cache)
    physical = tuple(csv.reader(io.StringIO(report), delimiter="\t"))[1][4]
    path.write_text(report, encoding="utf-8", newline="")

    # When
    loaded = load_description_cache(str(path))

    # Then: the physical report is safe while the trusted loader is byte-exact.
    assert physical != raw
    assert not physical.lstrip().startswith(("=", "+", "-", "@"))
    entry = loaded.lookup("物品", "ratf", "扩展提示", None)[0]
    assert entry.raw_value == raw
    assert entry.source_map_sha256 == expected.source_map_sha256
    assert entry.source_manifest_sha256 == expected.source_manifest_sha256


def test_standalone_cache_rejects_legacy_schema_and_symlinks(tmp_path: Path) -> None:
    # Given: a pre-manifest cache and a symlinked explicit cache path.
    legacy = tmp_path / "legacy.tsv"
    legacy.write_text(
        "分类\t基础ID\t文本角色\t等级/变体\t原始全文\t可读全文\t来源地图SHA256\t来源路径\n",
        encoding="utf-8",
    )
    linked = tmp_path / "linked.tsv"
    linked.symlink_to(legacy)

    # When / Then
    assert load_description_cache(str(legacy)).entries == ()
    assert "schema" in load_description_cache(str(legacy)).diagnostics[0]
    assert load_description_cache(str(linked)).entries == ()
