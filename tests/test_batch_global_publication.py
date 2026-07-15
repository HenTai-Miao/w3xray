"""Transactional global-generation publication and validation contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import w3xtool.batch_global_publication as global_publication
from w3xtool.batch_models import (
    BATCH_SCHEMA_VERSION,
    BatchState,
    MapBatchResult,
    MapBatchState,
    SourceFingerprint,
)
from w3xtool.description_cache import format_description_cache_tsv
from w3xtool.description_cache_models import EMPTY_DESCRIPTION_CACHE


def test_global_generation_round_trip_selects_only_validated_payloads(
    tmp_path: Path,
) -> None:
    # Given / When: all global reports are published as one generation.
    generation = global_publication.publish_global_generation(
        tmp_path,
        _state("a"),
        _cache_text(),
        '{"code":"started"}\n',
    )
    loaded = global_publication.load_current_generation(tmp_path)

    # Then: the pointer resolves the exact state and compatibility mirrors.
    assert loaded == generation
    assert global_publication.load_current_batch_state(tmp_path) == _state("a")
    assert (tmp_path / "批量提取状态.json").read_text(encoding="utf-8").endswith("\n")
    assert (tmp_path / "可信描述缓存.tsv").read_text(encoding="utf-8") == _cache_text()


def test_current_pointer_never_selects_a_partial_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: one committed generation and a later pointer publication failure.
    first = global_publication.publish_global_generation(
        tmp_path,
        _state("a"),
        _cache_text(),
        "",
    )

    def fail_pointer(*_args) -> None:
        raise OSError("pointer")

    monkeypatch.setattr(global_publication, "_publish_pointer", fail_pointer)

    # When / Then: the failed generation never becomes resume authority.
    with pytest.raises(OSError, match="pointer"):
        global_publication.publish_global_generation(
            tmp_path,
            _state("b"),
            _cache_text(),
            "",
        )
    assert global_publication.load_current_generation(tmp_path) == first


def test_generation_validation_rejects_same_size_report_tampering(
    tmp_path: Path,
) -> None:
    # Given: one committed generation whose diagnostics bytes are changed in place.
    generation = global_publication.publish_global_generation(
        tmp_path,
        _state("a"),
        _cache_text(),
        '{"code":"first"}\n',
    )
    diagnostics = generation.directory / "批量诊断.jsonl"
    diagnostics.write_bytes(b"X" * diagnostics.stat().st_size)

    # When / Then: current authority disappears instead of trusting equal size.
    assert global_publication.load_current_generation(tmp_path) is None
    assert global_publication.load_current_batch_state(tmp_path) is None


def test_generation_validation_rejects_unlisted_and_symlink_artifacts(
    tmp_path: Path,
) -> None:
    # Given: an otherwise valid immutable generation gains an unlisted file.
    generation = global_publication.publish_global_generation(
        tmp_path,
        _state("a"),
        _cache_text(),
        "",
    )
    (generation.directory / "extra.bin").write_bytes(b"extra")

    # When / Then
    assert global_publication.load_current_generation(tmp_path) is None


def test_current_pointer_rejects_traversal_and_manifest_hash_drift(
    tmp_path: Path,
) -> None:
    # Given: a valid pointer is replaced with a traversal target.
    generation = global_publication.publish_global_generation(
        tmp_path,
        _state("a"),
        _cache_text(),
        "",
    )
    pointer = tmp_path / ".w3xray-global" / "current.json"
    pointer.write_text(
        json.dumps(
            {
                "generation_id": "../escape",
                "manifest_sha256": generation.manifest_sha256,
                "schema_version": 1,
            }
        ),
        encoding="utf-8",
    )

    # When / Then
    assert global_publication.load_current_generation(tmp_path) is None


def test_compatibility_mirror_failure_keeps_new_authoritative_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a first generation and a failure after the second pointer commits.
    _ = global_publication.publish_global_generation(
        tmp_path,
        _state("a"),
        _cache_text(),
        "",
    )

    def fail_mirrors(*_args) -> None:
        raise OSError("mirror")

    monkeypatch.setattr(
        global_publication,
        "_publish_compatibility_mirrors",
        fail_mirrors,
    )

    # When: compatibility publication fails outside the authority boundary.
    with pytest.raises(OSError, match="mirror"):
        global_publication.publish_global_generation(
            tmp_path,
            _state("b"),
            _cache_text(),
            "",
        )

    # Then: resume still observes the fully validated second generation.
    loaded = global_publication.load_current_generation(tmp_path)
    assert loaded is not None
    assert loaded.state == _state("b")


def _state(label: str) -> BatchState:
    source_digest = ("a" if label == "a" else "b") * 64
    result = MapBatchResult(
        source=SourceFingerprint(f"/maps/{label}.w3x", 3, 4, source_digest),
        display_name=label,
        output_directory=f"地图/001_{label}_{source_digest[:8]}",
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
        elapsed_ms=1,
        dependency_fingerprint="d" * 64,
        manifest_sha256="e" * 64,
        published_bytes=1,
    )
    return BatchState(BATCH_SCHEMA_VERSION, (result,))


def _cache_text() -> str:
    return format_description_cache_tsv(EMPTY_DESCRIPTION_CACHE)
