"""Trusted, hash-bound historical icon cache tests."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path

import pytest

from w3xtool.game_data_source import open_game_data_source, probe_game_data_path
from w3xtool.icon_resources import TrustedIconEvidenceSource
from w3xtool.trusted_icon_cache import (
    TrustedIconCacheDataSource,
    TrustedIconCacheError,
)

_MAP_DIGEST = "a" * 64
_ICON_PATH = r"Icons\BTNHero.blp"
_ICON_PAYLOAD = b"BLP1trusted"


def test_trusted_icon_cache_opens_payload_and_map_bound_evidence(
    tmp_path: Path,
) -> None:
    # Given: an owned cache binds one client payload and one map digest to evidence.
    cache = _write_cache(tmp_path)

    # When: the unified game-data boundary opens the selected directory.
    probe = probe_game_data_path(str(cache))
    source = open_game_data_source(str(cache))

    # Then: exact bytes, provenance, and object references remain available.
    assert probe.kind == "trusted_icon_cache"
    assert source is not None
    assert isinstance(source, TrustedIconEvidenceSource)
    try:
        assert source.read_file(_ICON_PATH) == _ICON_PAYLOAD
        (resource,) = source.cached_icons_for(_MAP_DIGEST)
    finally:
        source.close()
    assert resource.requested_path == _ICON_PATH
    assert resource.resolved_path == _ICON_PATH
    assert resource.sha256 == hashlib.sha256(_ICON_PAYLOAD).hexdigest()
    assert resource.source_path.endswith("war3.mpq")
    assert tuple(
        (item.category, item.object_id, item.object_name) for item in resource.objects
    ) == (("技能", "A001", "暴风雪"),)


def test_trusted_icon_cache_rejects_conflicting_normalized_payloads(
    tmp_path: Path,
) -> None:
    # Given: the manifest assigns two different hashes to one virtual path.
    cache = _write_cache(tmp_path)
    manifest = cache / "可信图标缓存.tsv"
    with manifest.open("a", encoding="utf-8", newline="") as handle:
        csv.writer(handle, delimiter="\t", lineterminator="\n").writerow(
            (
                _ICON_PATH.lower(),
                "b" * 64,
                "war3x.mpq",
                "conflicting-output",
            )
        )

    # When/Then: the trust boundary refuses archive-order resolution.
    with pytest.raises(TrustedIconCacheError, match="conflicting virtual path"):
        TrustedIconCacheDataSource(str(cache))


def test_trusted_icon_cache_rejects_evidence_path_traversal(
    tmp_path: Path,
) -> None:
    # Given: map-bound evidence tries to publish an unsafe requested path.
    cache = _write_cache(tmp_path, requested_path=r"..\BTNHero.blp")
    source = TrustedIconCacheDataSource(str(cache))

    # When/Then: evidence parsing rejects the row before any payload is returned.
    with pytest.raises(TrustedIconCacheError, match="unsafe icon path"):
        source.cached_icons_for(_MAP_DIGEST)


def test_trusted_icon_cache_rejects_evidence_archive_mismatch(
    tmp_path: Path,
) -> None:
    # Given: evidence relabels a manifest payload as a different trusted archive.
    cache = _write_cache(tmp_path)
    evidence = cache / "地图图标证据" / f"{_MAP_DIGEST}.tsv"
    _write_tsv(
        evidence,
        (
            ("原始路径", "解析路径", "SHA256", "原客户端档案", "引用对象"),
            (
                _ICON_PATH,
                _ICON_PATH,
                hashlib.sha256(_ICON_PAYLOAD).hexdigest(),
                "war3patch.mpq",
                "技能:A001:暴风雪",
            ),
        ),
    )
    source = TrustedIconCacheDataSource(str(cache))

    # When/Then: provenance must match the payload manifest exactly.
    with pytest.raises(TrustedIconCacheError, match="archive mismatch"):
        source.cached_icons_for(_MAP_DIGEST)


def test_trusted_icon_cache_rejects_symlinked_evidence_parent(
    tmp_path: Path,
) -> None:
    # Given: the evidence directory is replaced by a link outside the cache root.
    cache = _write_cache(tmp_path)
    evidence_directory = cache / "地图图标证据"
    outside = tmp_path / "outside-evidence"
    evidence_directory.rename(outside)
    try:
        evidence_directory.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable")
    source = TrustedIconCacheDataSource(str(cache))

    # When/Then: the cache boundary rejects the parent link before reading TSV.
    with pytest.raises(TrustedIconCacheError, match="unsafe evidence path"):
        source.cached_icons_for(_MAP_DIGEST)


def _write_cache(
    root: Path,
    *,
    requested_path: str = _ICON_PATH,
) -> Path:
    cache = root / "trusted-icons"
    icon = cache / "Icons" / "BTNHero.blp"
    icon.parent.mkdir(parents=True)
    icon.write_bytes(_ICON_PAYLOAD)
    (cache / ".w3xray-trusted-icon-cache").write_text(
        "schema=2\n",
        encoding="ascii",
    )
    _write_tsv(
        cache / "可信图标缓存.tsv",
        (
            ("虚拟路径", "SHA256", "原客户端档案", "验证来源目录"),
            (
                _ICON_PATH,
                hashlib.sha256(_ICON_PAYLOAD).hexdigest(),
                "war3.mpq",
                "owned-output",
            ),
        ),
    )
    evidence = cache / "地图图标证据" / f"{_MAP_DIGEST}.tsv"
    evidence.parent.mkdir()
    _write_tsv(
        evidence,
        (
            ("原始路径", "解析路径", "SHA256", "原客户端档案", "引用对象"),
            (
                requested_path,
                _ICON_PATH,
                hashlib.sha256(_ICON_PAYLOAD).hexdigest(),
                "war3.mpq",
                "技能:A001:暴风雪",
            ),
        ),
    )
    return cache


def _write_tsv(path: Path, rows: tuple[tuple[str, ...], ...]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerows(rows)
