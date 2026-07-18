"""Transactional global-generation publication and validation contracts."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

import w3xtool.batch_global_publication as global_publication
from tests.batch_publication_fixture import publish_empty_result
from w3xtool.batch_global_io import format_global_manifest, parse_global_manifest
from w3xtool.batch_global_validation import validate_global_generation
from w3xtool.batch_models import (
    BATCH_SCHEMA_VERSION,
    BatchState,
    SourceFingerprint,
)
from w3xtool.description_cache import format_description_cache_tsv
from w3xtool.description_cache_models import EMPTY_DESCRIPTION_CACHE


def test_global_generation_round_trip_selects_only_validated_payloads(
    tmp_path: Path,
) -> None:
    # Given / When: all global reports are published as one generation.
    state = _state(tmp_path, "a")
    generation = global_publication.publish_global_generation(
        tmp_path,
        state,
        _cache_text(),
        '{"code":"started"}\n',
    )
    loaded = global_publication.load_current_generation(tmp_path)

    # Then: the pointer resolves the exact state and compatibility mirrors.
    assert loaded == generation
    assert generation.evidence.gaps == ()
    assert generation.evidence.candidates == ()
    manifest = json.loads((generation.directory / "全局清单.json").read_text("utf-8"))
    assert manifest["artifact_count"] == 9
    assert global_publication.load_current_batch_state(tmp_path) == state
    assert (tmp_path / "批量提取状态.json").read_text(encoding="utf-8").endswith("\n")
    assert (tmp_path / "可信描述缓存.tsv").read_text(encoding="utf-8") == _cache_text()
    assert (tmp_path / "图标缺口汇总.tsv").is_file()
    assert (tmp_path / "图标候选绑定.tsv").is_file()
    assert (tmp_path / "图标缺口统计.txt").is_file()
    assert (tmp_path / "三轴状态汇总.tsv").is_file()


def test_current_pointer_never_selects_a_partial_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: one committed generation and a later pointer publication failure.
    first_state = _state(tmp_path, "a")
    first = global_publication.publish_global_generation(
        tmp_path,
        first_state,
        _cache_text(),
        "",
    )

    def fail_pointer(*_args) -> None:
        raise OSError("pointer")

    monkeypatch.setattr(global_publication, "_publish_pointer", fail_pointer)
    second_state = _state(tmp_path, "b")

    # When / Then: the failed generation never becomes resume authority.
    with pytest.raises(OSError, match="pointer"):
        global_publication.publish_global_generation(
            tmp_path,
            second_state,
            _cache_text(),
            "",
        )
    assert global_publication.load_current_generation(tmp_path) == first


def test_generation_validation_rejects_same_size_report_tampering(
    tmp_path: Path,
) -> None:
    # Given: one committed generation whose diagnostics bytes are changed in place.
    state = _state(tmp_path, "a")
    generation = global_publication.publish_global_generation(
        tmp_path,
        state,
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
    state = _state(tmp_path, "a")
    generation = global_publication.publish_global_generation(
        tmp_path,
        state,
        _cache_text(),
        "",
    )
    (generation.directory / "extra.bin").write_bytes(b"extra")

    # When / Then
    assert global_publication.load_current_generation(tmp_path) is None


@pytest.mark.parametrize(
    "name",
    (
        "图标缺口汇总.tsv",
        "图标候选绑定.tsv",
        "图标缺口统计.txt",
        "三轴状态汇总.tsv",
    ),
)
def test_generation_validation_reconciles_each_global_evidence_report(
    tmp_path: Path,
    name: str,
) -> None:
    # Given: a report and its manifest hash agree on noncanonical extra bytes.
    state = _state(tmp_path, "a")
    generation = global_publication.publish_global_generation(
        tmp_path, state, _cache_text(), ""
    )
    report = generation.directory / name
    report.write_text(report.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    _rebind_manifest_artifact(generation.directory, name)

    # When / Then: semantic byte-for-byte reconstruction still rejects it.
    assert validate_global_generation(generation.directory) is None


def test_current_pointer_rejects_traversal_and_manifest_hash_drift(
    tmp_path: Path,
) -> None:
    # Given: a valid pointer is replaced with a traversal target.
    state = _state(tmp_path, "a")
    generation = global_publication.publish_global_generation(
        tmp_path,
        state,
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
    first_state = _state(tmp_path, "a")
    _ = global_publication.publish_global_generation(
        tmp_path,
        first_state,
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
    second_state = _state(tmp_path, "b")

    # When: compatibility publication fails outside the authority boundary.
    with pytest.raises(OSError, match="mirror"):
        global_publication.publish_global_generation(
            tmp_path,
            second_state,
            _cache_text(),
            "",
        )

    # Then: resume still observes the fully validated second generation.
    loaded = global_publication.load_current_generation(tmp_path)
    assert loaded is not None
    assert loaded.state == second_state


def _state(output_root: Path, label: str) -> BatchState:
    source_digest = ("a" if label == "a" else "b") * 64
    result = publish_empty_result(
        1,
        SourceFingerprint(f"/maps/{label}.w3x", 3, 4, source_digest),
        str(output_root),
    )
    return BatchState(BATCH_SCHEMA_VERSION, (result,))


def _cache_text() -> str:
    return format_description_cache_tsv(EMPTY_DESCRIPTION_CACHE)


def _rebind_manifest_artifact(directory: Path, name: str) -> None:
    manifest_path = directory / "全局清单.json"
    manifest = parse_global_manifest(manifest_path.read_text(encoding="utf-8"))
    payload = (directory / name).read_bytes()
    artifacts = tuple(
        replace(
            artifact,
            size=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
        )
        if artifact.name == name
        else artifact
        for artifact in manifest.artifacts
    )
    updated = replace(
        manifest,
        artifacts=artifacts,
        total_size=sum(artifact.size for artifact in artifacts),
    )
    manifest_path.write_text(format_global_manifest(updated), encoding="utf-8")
