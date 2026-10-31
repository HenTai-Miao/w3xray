"""Complete fields and stable file generations for current cache readers."""

from __future__ import annotations

import csv
import os
from pathlib import Path
import stat

import pytest

from gametool import trusted_description_cache_path as cache_paths
from gametool.batch_tsv import format_tsv_rows
from gametool.bounded_file import (
    BoundedFileError,
    read_bounded_regular_file,
    sha256_regular_file,
)
from gametool.description_cache import load_description_cache
from gametool.description_cache_migration_models import DescriptionCacheRejectionReason
from gametool.description_cache_schema import (
    DESCRIPTION_CACHE_REJECTION_HEADER,
    DESCRIPTION_CACHE_SOURCE_HEADER,
)
from gametool.trusted_description_cache import (
    TrustedDescriptionCacheError,
    load_trusted_description_cache,
)
from gametool.trusted_description_cache_tables import (
    parse_source_manifest,
    validate_rejection_table,
)
from tests.trusted_description_cache_fixture import published_cache


def test_owned_and_standalone_cache_keep_fields_beyond_csv_default(
    tmp_path: Path,
) -> None:
    # The source report, candidate proof, owned table and standalone loader all
    # carry the same field; no intermediate parser may silently drop that entry.
    raw = "完整描述" * 40_000
    previous = csv.field_size_limit()
    root = published_cache(tmp_path, raw=raw)

    owned = load_trusted_description_cache(root)
    standalone = load_description_cache(str(root / "可信描述缓存.tsv"))

    assert owned.cache.entries == standalone.entries
    assert owned.cache.entries[0].raw_value == raw
    assert owned.cache.entries[0].readable_value == raw
    assert csv.field_size_limit() == previous


def test_source_and_rejection_tables_keep_complete_long_fields() -> None:
    text = "全量来源" * 40_000 + '\t"引用"\r\n下一段'
    source_row = (
        "物品",
        "ratf",
        "扩展提示",
        "",
        "a" * 64,
        text,
        "b" * 64,
        "2",
        "c" * 64,
        "base:ratf",
    )
    rejection_row = (
        "物品",
        "ratf",
        "扩展提示",
        "",
        text,
        text,
        "a" * 64,
        "report",
        DescriptionCacheRejectionReason.SOURCE_ROW_MISSING.value,
        text,
        "2",
    )
    previous = csv.field_size_limit()

    (source,) = parse_source_manifest(
        format_tsv_rows((DESCRIPTION_CACHE_SOURCE_HEADER, source_row)).encode()
    )
    validate_rejection_table(
        format_tsv_rows((DESCRIPTION_CACHE_REJECTION_HEADER, rejection_row)).encode()
    )

    assert source.report_path == text
    assert csv.field_size_limit() == previous


def test_owned_cache_rechecks_complete_inventory_after_last_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = published_cache(tmp_path)
    original = cache_paths._read_stable

    def insert_late_file(path: Path, maximum: int | None) -> bytes:
        payload = original(path, maximum)
        if path.name == "可信缓存迁移拒绝.tsv":
            (root / "unexpected.tsv").write_bytes(b"foreign evidence")
        return payload

    monkeypatch.setattr(cache_paths, "_read_stable", insert_late_file)

    with pytest.raises(TrustedDescriptionCacheError, match="partial|unsafe"):
        load_trusted_description_cache(root)
    assert (root / "unexpected.tsv").read_bytes() == b"foreign evidence"


def test_owned_cache_holds_earlier_leaf_until_complete_read_finishes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = published_cache(tmp_path)
    marker = root / ".gamexray-trusted-description-cache"
    expected = marker.read_bytes()
    original = cache_paths._read_stable
    blocked = False

    def rewrite_earlier_leaf(path: Path, maximum: int | None) -> bytes:
        nonlocal blocked
        payload = original(path, maximum)
        if path.name == "可信缓存迁移拒绝.tsv":
            try:
                marker.write_bytes(b"x" * len(expected))
            except OSError:
                blocked = True
        return payload

    monkeypatch.setattr(cache_paths, "_read_stable", rewrite_earlier_leaf)

    if os.name == "nt":
        verified = load_trusted_description_cache(root)
        assert blocked
        assert len(verified.cache.entries) == 1
        assert marker.read_bytes() == expected
    else:
        with pytest.raises(TrustedDescriptionCacheError, match="generation changed"):
            load_trusted_description_cache(root)


def test_owned_cache_holds_root_until_complete_read_finishes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = published_cache(tmp_path)
    displaced = root.with_name("displaced-cache")
    original = cache_paths._read_stable
    blocked = False

    def replace_root(path: Path, maximum: int | None) -> bytes:
        nonlocal blocked
        payload = original(path, maximum)
        if path.name == "可信缓存迁移拒绝.tsv":
            try:
                root.rename(displaced)
            except OSError:
                blocked = True
            else:
                root.mkdir()
                for leaf in displaced.iterdir():
                    (root / leaf.name).write_bytes(leaf.read_bytes())
        return payload

    monkeypatch.setattr(cache_paths, "_read_stable", replace_root)

    if os.name == "nt":
        verified = load_trusted_description_cache(root)
        assert blocked
        assert len(verified.cache.entries) == 1
        assert not displaced.exists()
    else:
        with pytest.raises(TrustedDescriptionCacheError, match="generation changed"):
            load_trusted_description_cache(root)


@pytest.mark.parametrize("hash_only", (False, True))
def test_regular_file_read_rechecks_named_mode_at_final_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    hash_only: bool,
) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"complete payload")
    previous_mode = source.stat().st_mode
    original = os.lstat
    calls = 0

    def change_mode_at_final_stat(path: str | os.PathLike[str]) -> os.stat_result:
        nonlocal calls
        calls += 1
        if calls == 2:
            source.chmod(stat.S_IREAD)
        return original(path)

    monkeypatch.setattr("gametool.bounded_file.os.lstat", change_mode_at_final_stat)
    try:
        with pytest.raises(BoundedFileError, match="metadata changed"):
            if hash_only:
                sha256_regular_file(source)
            else:
                read_bounded_regular_file(source)
    finally:
        source.chmod(previous_mode)
