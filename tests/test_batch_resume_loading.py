"""Authoritative global-generation loading contracts for batch resume."""

from __future__ import annotations

import json
from pathlib import Path

from tests.batch_publication_fixture import publish_empty_result
from w3xtool.batch_global_publication import publish_global_generation
from w3xtool.batch_models import (
    BATCH_SCHEMA_VERSION,
    BatchState,
    MapBatchResult,
    SourceFingerprint,
)
from w3xtool.batch_reports import format_batch_state_json
from w3xtool.batch_resume import (
    ResumeDiagnostic,
    format_resume_diagnostics_jsonl,
    load_previous_state,
)
from w3xtool.description_cache import format_description_cache_tsv
from w3xtool.description_cache_models import EMPTY_DESCRIPTION_CACHE


def test_validated_current_generation_is_the_only_loaded_state(
    tmp_path: Path,
) -> None:
    # Given
    result = _published_result(tmp_path)
    expected = BatchState(BATCH_SCHEMA_VERSION, (result,))
    _ = publish_global_generation(tmp_path, expected, _cache_text(), "")
    (tmp_path / "批量提取状态.json").write_text("corrupt mirror", encoding="utf-8")

    # When
    previous = load_previous_state(str(tmp_path))

    # Then
    assert previous.state == expected
    assert previous.diagnostics == ()


def test_invalid_current_pointer_is_reported_and_never_falls_back(
    tmp_path: Path,
) -> None:
    # Given
    result = _published_result(tmp_path)
    state = BatchState(BATCH_SCHEMA_VERSION, (result,))
    _ = publish_global_generation(tmp_path, state, _cache_text(), "")
    pointer = tmp_path / ".w3xray-global" / "current.json"
    pointer.write_text("{}\n", encoding="utf-8")

    # When
    previous = load_previous_state(str(tmp_path))

    # Then
    assert previous.state is None
    assert tuple(item.code for item in previous.diagnostics) == (
        "invalid_global_generation",
    )


def test_legacy_root_state_is_reported_but_not_loaded(tmp_path: Path) -> None:
    # Given
    result = _published_result(tmp_path)
    state = BatchState(BATCH_SCHEMA_VERSION, (result,))
    (tmp_path / "批量提取状态.json").write_text(
        format_batch_state_json(state),
        encoding="utf-8",
    )

    # When
    previous = load_previous_state(str(tmp_path))

    # Then
    assert previous.state is None
    assert tuple(item.code for item in previous.diagnostics) == (
        "legacy_state_ignored",
    )


def test_empty_output_has_no_resume_corruption_diagnostic(tmp_path: Path) -> None:
    # When
    previous = load_previous_state(str(tmp_path))

    # Then
    assert previous.state is None
    assert previous.diagnostics == ()


def test_resume_diagnostics_are_lossless_json_lines() -> None:
    # Given
    diagnostics = (
        ResumeDiagnostic("publication_invalid", "hash\tmismatch\r\n", "/maps/a"),
    )

    # When
    text = format_resume_diagnostics_jsonl(diagnostics)

    # Then
    assert text.endswith("\n")
    assert json.loads(text) == {
        "code": "publication_invalid",
        "detail": "hash\tmismatch\r\n",
        "source_path": "/maps/a",
    }


def _published_result(tmp_path: Path) -> MapBatchResult:
    fingerprint = SourceFingerprint(str(tmp_path / "a.w3x"), 3, 4, "a" * 64)
    return publish_empty_result(1, fingerprint, str(tmp_path))


def _cache_text() -> str:
    return format_description_cache_tsv(EMPTY_DESCRIPTION_CACHE)
