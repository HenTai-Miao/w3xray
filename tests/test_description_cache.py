"""Validated manifest-bound base-object description cache contracts."""

from __future__ import annotations

from pathlib import Path

from tests.batch_publication_fixture import publish_client_fill_result
from w3xtool.batch_models import SourceFingerprint
from w3xtool.description_cache import (
    build_description_cache_from_batch,
    format_description_cache_tsv,
    load_description_cache,
)


def test_batch_cache_accepts_only_manifest_valid_client_fill_rows(
    tmp_path: Path,
) -> None:
    # Given: one valid generation has two client roles and one legacy marker lies.
    published = publish_client_fill_result(
        1,
        _fingerprint("a"),
        str(tmp_path),
        values=(("基础提示", "基础提示"), ("扩展提示", "完整说明")),
    )
    legacy = tmp_path / "地图" / "legacy"
    legacy.mkdir()
    (legacy / ".w3xray-batch-owned").write_text("b" * 64, encoding="ascii")
    (legacy / "对象描述.tsv").write_text("legacy\n", encoding="utf-8")

    # When
    cache = build_description_cache_from_batch(tmp_path)

    # Then
    assert cache.lookup("物品", "ratf", "基础提示", None)[0].raw_value == "基础提示"
    entry = cache.lookup("物品", "ratf", "扩展提示", None)[0]
    assert entry.raw_value == "完整说明"
    assert entry.source_manifest_sha256 == published.manifest_sha256
    assert any("manifest_validation_failed" in item for item in cache.diagnostics)


def test_batch_cache_removes_a_key_when_valid_generations_disagree(
    tmp_path: Path,
) -> None:
    # Given: two fully validated generations disagree byte-for-byte on one key.
    _ = publish_client_fill_result(
        1,
        _fingerprint("b"),
        str(tmp_path),
        values=(("扩展提示", "甲"),),
    )
    _ = publish_client_fill_result(
        2,
        _fingerprint("c"),
        str(tmp_path),
        values=(("扩展提示", "乙"),),
    )

    # When
    cache = build_description_cache_from_batch(tmp_path)

    # Then
    assert cache.lookup("物品", "ratf", "扩展提示", None) == ()
    assert cache.conflict_count == 1
    assert any("物品/ratf/扩展提示" in item for item in cache.diagnostics)


def test_formatted_cache_round_trips_all_text_and_both_source_hashes(
    tmp_path: Path,
) -> None:
    # Given: raw text contains TSV controls, quotes, newlines, and edge spaces.
    raw = '  "开头\t正文\r\n第二行  '
    published = publish_client_fill_result(
        1,
        _fingerprint("d"),
        str(tmp_path),
        values=(("扩展提示", raw),),
    )
    cache = build_description_cache_from_batch(tmp_path)
    path = tmp_path / "可信描述缓存.tsv"
    path.write_text(format_description_cache_tsv(cache), encoding="utf-8", newline="")

    # When
    loaded = load_description_cache(str(path))

    # Then
    entry = loaded.lookup("物品", "ratf", "扩展提示", None)[0]
    assert entry.raw_value == raw
    assert entry.source_map_sha256 == published.source.sha256
    assert entry.source_manifest_sha256 == published.manifest_sha256


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


def _fingerprint(character: str) -> SourceFingerprint:
    return SourceFingerprint(
        f"/maps/{character}.w3x",
        3,
        4,
        character * 64,
    )
