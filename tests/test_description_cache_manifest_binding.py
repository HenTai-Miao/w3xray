"""Manifest-bound trusted description cache discovery and seeding."""

from __future__ import annotations

from pathlib import Path
import shutil

from tests.batch_publication_fixture import publish_client_fill_result
from w3xtool.batch_description_cache import build_and_publish_description_cache
from w3xtool.batch_global_publication import publish_global_generation
from w3xtool.batch_models import (
    BATCH_SCHEMA_VERSION,
    BatchState,
    MapBatchResult,
    SourceFingerprint,
)
from w3xtool.description_cache import (
    EMPTY_DESCRIPTION_CACHE,
    build_description_cache_from_batch,
    format_description_cache_tsv,
)


def test_batch_cache_entry_is_bound_to_validated_map_manifest(
    tmp_path: Path,
) -> None:
    # Given: a valid map publication contains one trusted client-fill row.
    published = _publish_client_fill(tmp_path)

    # When: cache discovery validates the complete directory first.
    cache = build_description_cache_from_batch(tmp_path)

    # Then: the entry records both source map and exact source manifest hashes.
    entry = cache.lookup("物品", "ratf", "扩展提示", None)[0]
    assert entry.raw_value == "完整说明"
    assert entry.source_map_sha256 == published.source.sha256
    assert entry.source_manifest_sha256 == published.manifest_sha256


def test_batch_cache_ignores_tampered_report_with_stable_diagnostic(
    tmp_path: Path,
) -> None:
    # Given: a valid publication is changed after its manifest commits.
    published = _publish_client_fill(tmp_path)
    report = tmp_path / published.output_directory / "对象完整描述.tsv"
    report.write_bytes(b"X" * report.stat().st_size)

    # When
    cache = build_description_cache_from_batch(tmp_path)

    # Then: no row is trusted and the reason remains machine-searchable.
    assert cache.entries == ()
    assert any(
        "manifest_validation_failed" in diagnostic for diagnostic in cache.diagnostics
    )


def test_automatic_seed_is_loaded_only_from_validated_global_generation(
    tmp_path: Path,
) -> None:
    # Given: a validated map produces a cache, then a global generation commits it.
    published = _publish_client_fill(tmp_path)
    cache = build_description_cache_from_batch(tmp_path)
    cache_text = format_description_cache_tsv(cache)
    _ = publish_global_generation(
        tmp_path,
        BatchState(BATCH_SCHEMA_VERSION, (published,)),
        cache_text,
        "",
    )
    map_root = tmp_path / "地图"
    shutil.rmtree(map_root)
    (tmp_path / "可信描述缓存.tsv").write_text(
        format_description_cache_tsv(EMPTY_DESCRIPTION_CACHE),
        encoding="utf-8",
    )

    # When: the next run rebuilds with no map reports remaining.
    rebuilt = build_and_publish_description_cache(str(tmp_path))

    # Then: only the validated pointed generation supplies the seed.
    assert rebuilt.lookup("物品", "ratf", "扩展提示", None)[0].raw_value == "完整说明"


def _publish_client_fill(root: Path) -> MapBatchResult:
    fingerprint = SourceFingerprint("/maps/sample.w3x", 3, 4, "a" * 64)
    return publish_client_fill_result(1, fingerprint, str(root))
