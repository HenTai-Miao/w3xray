"""Validation tests for owned trusted-description cache generations."""

from __future__ import annotations

from collections.abc import Iterator
import hashlib
import importlib.util
import os
from pathlib import Path

import pytest

from tests.description_cache_migration_fixture import (
    LEGACY_RELATIVE,
    legacy_client_fill,
)
from tests.source_parent_swap_fixture import swapping_open
from tests.trusted_description_cache_fixture import (
    published_cache,
    resign_source_evidence,
    rewrite_source_record,
)
from w3xtool import trusted_description_cache as trusted_cache
from w3xtool.batch_tsv import format_tsv_rows
from w3xtool.bounded_file import FileIdentity
from w3xtool.description_cache_schema import LEGACY_DESCRIPTION_HEADER
from w3xtool.trusted_description_cache import (
    TrustedDescriptionCacheError,
    load_trusted_description_cache,
)


def test_trusted_description_cache_loader_boundary_exists() -> None:
    # Given: Task 5 requires an explicit owned-cache trust boundary.
    module_name = "w3xtool.trusted_description_cache"

    # When
    specification = importlib.util.find_spec(module_name)

    # Then
    assert specification is not None


def test_trusted_loader_accepts_complete_owned_cache(tmp_path: Path) -> None:
    # Given: migration published a complete cache through its real boundary.
    root = published_cache(tmp_path)

    # When
    verified = load_trusted_description_cache(root)

    # Then
    entry = verified.cache.lookup("物品", "ratf", "扩展提示", None)[0]
    assert entry.raw_value == "原版说明"
    assert len(verified.manifest_sha256) == 64
    assert len(verified.content_sha256) == 64


def test_trusted_cache_rejects_source_manifest_tampering(tmp_path: Path) -> None:
    # Given: one bound payload changes after publication.
    root = published_cache(tmp_path)
    source_manifest = root / "来源清单.tsv"
    source_manifest.write_bytes(source_manifest.read_bytes() + b"tamper")

    # When / Then
    with pytest.raises(TrustedDescriptionCacheError, match="hash mismatch"):
        load_trusted_description_cache(root)


@pytest.mark.parametrize(
    ("name", "expected"),
    (
        ("可信描述缓存.tsv", "payload hash mismatch"),
        ("内容清单.json", "manifest hash mismatch"),
        (".w3xray-trusted-description-cache", "invalid owned metadata"),
    ),
)
def test_trusted_cache_rejects_cache_manifest_and_marker_tampering(
    tmp_path: Path,
    name: str,
    expected: str,
) -> None:
    # Given: one owned cache or metadata file changes without its binding.
    root = published_cache(tmp_path)
    target = root / name
    target.write_bytes(target.read_bytes() + b"tamper")

    # When / Then
    with pytest.raises(TrustedDescriptionCacheError, match=expected):
        load_trusted_description_cache(root)


@pytest.mark.parametrize("mutation", ("missing", "symlink", "extra"))
def test_trusted_cache_rejects_partial_or_unsafe_payload_inventory(
    tmp_path: Path,
    mutation: str,
) -> None:
    # Given: the exact five-file inventory is missing, linked, or extended.
    root = published_cache(tmp_path)
    payload = root / "可信描述缓存.tsv"
    if mutation == "missing":
        payload.unlink()
    elif mutation == "symlink":
        moved = tmp_path / "cache.real.tsv"
        moved.write_bytes(payload.read_bytes())
        payload.unlink()
        payload.symlink_to(moved)
    else:
        (root / "extra").write_text("foreign", encoding="utf-8")

    # When / Then
    with pytest.raises(TrustedDescriptionCacheError, match="partial|unsafe"):
        load_trusted_description_cache(root)


def test_trusted_cache_rehashes_original_source_report(tmp_path: Path) -> None:
    # Given: payloads are intact but the historical report no longer hashes exactly.
    root = published_cache(tmp_path)
    report = tmp_path / "legacy-output" / LEGACY_RELATIVE / "对象描述.tsv"
    report.write_bytes(report.read_bytes() + b"tamper")

    # When / Then
    with pytest.raises(TrustedDescriptionCacheError, match="source.*hash mismatch"):
        load_trusted_description_cache(root)


def test_trusted_cache_rejects_symlinked_source_report(tmp_path: Path) -> None:
    # Given: the bound source path is replaced by a symlink to identical bytes.
    root = published_cache(tmp_path)
    report = tmp_path / "legacy-output" / LEGACY_RELATIVE / "对象描述.tsv"
    moved = report.with_suffix(".real.tsv")
    report.replace(moved)
    report.symlink_to(moved)

    # When / Then
    with pytest.raises(TrustedDescriptionCacheError, match="regular|symlink"):
        load_trusted_description_cache(root)


def test_trusted_replay_rejects_intermediate_source_parent_swapped_during_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: an owned cache whose source parent becomes a symlink at open time.
    root = published_cache(tmp_path)
    report = tmp_path / "legacy-output" / LEGACY_RELATIVE / "对象描述.tsv"
    source_parent = tmp_path / "legacy-output" / "地图"
    moved_parent = tmp_path / "moved-map-parent"
    events: list[str] = []
    monkeypatch.setattr(
        os,
        "open",
        swapping_open(os.open, source_parent, moved_parent, report, events),
    )

    # When / Then: replay must walk from its held root fd without following it.
    with pytest.raises(TrustedDescriptionCacheError, match="source|symlink|regular"):
        _ = load_trusted_description_cache(root)
    assert events == ["parent swapped"]


def test_trusted_cache_rejects_resigned_source_path_escape(tmp_path: Path) -> None:
    # Given: an attacker re-signs all owned metadata around an outside report path.
    root = published_cache(tmp_path)
    report = tmp_path / "legacy-output" / LEGACY_RELATIVE / "对象描述.tsv"
    outside = tmp_path / "outside.tsv"
    outside.write_bytes(report.read_bytes())
    rewrite_source_record(root, report_path=str(outside))
    resign_source_evidence(root)

    # When / Then: re-signing does not expand the published source root.
    with pytest.raises(TrustedDescriptionCacheError, match="escape.*source root"):
        load_trusted_description_cache(root)


def test_trusted_cache_rejects_resigned_source_row_number_digest_mismatch(
    tmp_path: Path,
) -> None:
    # Given: the table names row 3 while retaining the authentic digest of row 2.
    root = published_cache(tmp_path)
    report = tmp_path / "legacy-output" / LEGACY_RELATIVE / "对象描述.tsv"
    report.write_text(
        format_tsv_rows(
            (
                LEGACY_DESCRIPTION_HEADER,
                legacy_client_fill(),
                legacy_client_fill(
                    raw_description="另一行",
                    readable_description="另一行",
                ),
            )
        ),
        encoding="utf-8",
        newline="",
    )
    report_digest = hashlib.sha256(report.read_bytes()).hexdigest()
    rewrite_source_record(
        root,
        report_sha256=report_digest,
        report_row_number=3,
    )
    resign_source_evidence(root)

    # When / Then
    with pytest.raises(TrustedDescriptionCacheError, match="row hash mismatch"):
        load_trusted_description_cache(root)


def test_trusted_cache_rejects_owned_file_changing_between_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: one owned file returns different bytes under a stable identity.
    root = published_cache(tmp_path)
    identity = FileIdentity(1, 2, 5)
    payloads: Iterator[bytes] = iter((b"first", b"other"))

    def unstable_read(
        _path: Path,
        _maximum: int,
        *,
        expected: FileIdentity | None = None,
    ) -> tuple[bytes, FileIdentity]:
        if expected is not None:
            assert expected == identity
        return next(payloads), identity

    monkeypatch.setattr(trusted_cache, "read_bounded_regular_file", unstable_read)

    # When / Then
    with pytest.raises(TrustedDescriptionCacheError, match="changed while reading"):
        load_trusted_description_cache(root)


def test_trusted_cache_rejects_source_file_changing_between_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a bound historical report changes during its stable double-read.
    root = published_cache(tmp_path)
    report = tmp_path / "legacy-output" / LEGACY_RELATIVE / "对象描述.tsv"
    original = report.read_bytes()
    changed = b"X" + original[1:]
    real_lseek = os.lseek
    rewinds = 0

    def change_before_second_read(
        descriptor: int,
        position: int,
        how: int,
    ) -> int:
        nonlocal rewinds
        if position == 0 and how == os.SEEK_SET:
            rewinds += 1
            if rewinds == 2:
                _ = report.write_bytes(changed)
        return real_lseek(descriptor, position, how)

    monkeypatch.setattr(os, "lseek", change_before_second_read)

    # When / Then
    with pytest.raises(TrustedDescriptionCacheError, match="changed"):
        _ = load_trusted_description_cache(root)
