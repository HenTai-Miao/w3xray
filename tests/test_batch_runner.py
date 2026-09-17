"""Sequential batch orchestration and resume tests."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import assert_never

import pytest

from tests.batch_publication_fixture import publish_empty_result
import w3xtool.batch_map_attempt as batch_map_attempt
import w3xtool.batch_runner as batch_runner
from w3xtool.batch_models import (
    MapBatchResult,
    MapBatchState,
    SourceFingerprint,
)
from w3xtool.batch_runner import (
    BatchConfigurationError,
    BatchOptions,
    run_batch,
)
from w3xtool.batch_status import PublicationResult, derive_batch_axes
from w3xtool.load_context import MapLoadContext
from w3xtool.map_directory import scan_map_sources


def _write_map(path: Path, payload: bytes = b"map") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _result(
    fingerprint: SourceFingerprint,
    *,
    output_directory: str,
    state: MapBatchState = MapBatchState.COMPLETE,
) -> MapBatchResult:
    match state:
        case MapBatchState.COMPLETE:
            publication = PublicationResult.PUBLISHED
        case MapBatchState.FAILED:
            publication = PublicationResult.FAILED
        case MapBatchState.PARTIAL | MapBatchState.RESTRICTED | MapBatchState.CANCELLED:
            raise AssertionError("runner fixture supports complete or failed results")
        case unreachable:
            assert_never(unreachable)
    axes = derive_batch_axes(
        publication,
        raw_blocks=0,
        damaged_blocks=0,
        restricted_blocks=0,
        icon_gaps=0,
        current_text_states=(),
        relation_partial_count=0,
        unresolved_endpoint_count=0,
    )
    return MapBatchResult(
        source=fingerprint,
        display_name=Path(fingerprint.path).stem,
        output_directory=output_directory,
        stage="published" if state is not MapBatchState.FAILED else "load",
        state=state,
        first_error="" if state is not MapBatchState.FAILED else "broken",
        object_count=0,
        description_counts=(),
        named_icon_count=0,
        anonymous_icon_count=0,
        original_written_count=0,
        png_written_count=0,
        icon_failure_count=0,
        restricted_block_count=0,
        elapsed_ms=1,
        publication_result=axes.publication,
        archive_integrity=axes.archive,
        knowledge_evidence=axes.knowledge,
        knowledge_gap_reasons=axes.knowledge_reasons,
        raw_block_count=0,
        damaged_block_count=0,
        valid_icon_reference_count=0,
        resolved_icon_reference_count=0,
        filtered_icon_field_count=0,
        unresolved_icon_count=0,
        unresolved_icon_reference_count=0,
        anonymous_read_failure_count=0,
        original_write_failure_count=0,
        png_failure_count=0,
        dependency_fingerprint=fingerprint.sha256,
    )


def _publish_fake_result(
    index: int,
    fingerprint: SourceFingerprint,
    options: BatchOptions,
    _context: MapLoadContext,
) -> MapBatchResult:
    return publish_empty_result(index, fingerprint, options.output_root)


def test_scan_map_sources_includes_campaigns_in_stable_path_order(
    tmp_path: Path,
) -> None:
    # Given
    for name in ("z.w3n", "A.w3x", "nested/b.w3m", "ignored.txt"):
        _write_map(tmp_path / name)

    # When
    sources = scan_map_sources(str(tmp_path))

    # Then
    assert tuple(Path(path).relative_to(tmp_path).as_posix() for path in sources) == (
        "A.w3x",
        "nested/b.w3m",
        "z.w3n",
    )


def test_batch_continues_after_one_map_fails_and_does_not_modify_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    source_root = tmp_path / "Maps"
    bad = _write_map(source_root / "a_bad.w3x", b"bad")
    good = _write_map(source_root / "b_good.w3x", b"good")
    before = {
        path: (
            path.stat().st_size,
            path.stat().st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in (bad, good)
    }
    monkeypatch.setattr(
        batch_runner, "build_map_load_context", lambda **_kwargs: MapLoadContext()
    )

    def process(
        index: int,
        fingerprint: SourceFingerprint,
        options: BatchOptions,
        context: MapLoadContext,
    ) -> MapBatchResult:
        if Path(fingerprint.path) == bad:
            raise OSError("broken map")
        return _publish_fake_result(index, fingerprint, options, context)

    monkeypatch.setattr(batch_runner, "process_one_map", process)

    # When
    state = run_batch(BatchOptions(str(source_root), str(tmp_path / "output")))

    # Then
    assert [result.state for result in state.results] == [
        MapBatchState.FAILED,
        MapBatchState.COMPLETE,
    ]
    after = {
        path: (
            path.stat().st_size,
            path.stat().st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in (bad, good)
    }
    assert after == before


def test_resume_skips_only_an_unchanged_published_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    source_root = tmp_path / "Maps"
    _write_map(source_root / "sample.w3x")
    calls = 0
    monkeypatch.setattr(
        batch_runner, "build_map_load_context", lambda **_kwargs: MapLoadContext()
    )
    monkeypatch.setattr(
        batch_map_attempt,
        "fingerprint_dependencies",
        lambda source, *_args: source.sha256,
    )

    def process(
        index: int,
        fingerprint: SourceFingerprint,
        options: BatchOptions,
        context: MapLoadContext,
    ) -> MapBatchResult:
        nonlocal calls
        calls += 1
        return _publish_fake_result(index, fingerprint, options, context)

    monkeypatch.setattr(batch_runner, "process_one_map", process)
    options = BatchOptions(str(source_root), str(tmp_path / "output"))
    first = run_batch(options)

    # When
    second = run_batch(options)

    # Then
    assert second == first
    assert calls == 1


def test_resume_reprocesses_a_changed_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    source_root = tmp_path / "Maps"
    source = _write_map(source_root / "sample.w3x", b"first")
    calls = 0
    monkeypatch.setattr(
        batch_runner, "build_map_load_context", lambda **_kwargs: MapLoadContext()
    )

    def process(
        index: int,
        fingerprint: SourceFingerprint,
        options: BatchOptions,
        context: MapLoadContext,
    ) -> MapBatchResult:
        nonlocal calls
        calls += 1
        return _publish_fake_result(index, fingerprint, options, context)

    monkeypatch.setattr(batch_runner, "process_one_map", process)
    options = BatchOptions(str(source_root), str(tmp_path / "output"))
    _ = run_batch(options)
    source.write_bytes(b"second")
    os.utime(source, None)

    # When
    state = run_batch(options)

    # Then
    assert calls == 2
    assert state.results[0].source.sha256 == hashlib.sha256(b"second").hexdigest()


def test_batch_rejects_an_output_nested_in_the_source_tree(tmp_path: Path) -> None:
    # Given
    source_root = tmp_path / "Maps"
    _write_map(source_root / "sample.w3x")
    options = BatchOptions(str(source_root), str(source_root / "output"))

    # When / Then
    with pytest.raises(BatchConfigurationError, match="overlap"):
        run_batch(options)


def test_no_retry_failed_reuses_an_unchanged_failed_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    source_root = tmp_path / "Maps"
    _write_map(source_root / "broken.w3x")
    calls = 0
    monkeypatch.setattr(
        batch_runner, "build_map_load_context", lambda **_kwargs: MapLoadContext()
    )
    monkeypatch.setattr(
        batch_map_attempt,
        "fingerprint_dependencies",
        lambda source, *_args: source.sha256,
    )

    def fail(
        _index: int,
        fingerprint: SourceFingerprint,
        _options: BatchOptions,
        _context: MapLoadContext,
    ) -> MapBatchResult:
        nonlocal calls
        calls += 1
        return _result(fingerprint, output_directory="", state=MapBatchState.FAILED)

    monkeypatch.setattr(batch_runner, "process_one_map", fail)
    options = BatchOptions(
        str(source_root),
        str(tmp_path / "output"),
        retry_failed=False,
    )
    first = run_batch(options)

    # When
    second = run_batch(options)

    # Then
    assert second == first
    assert calls == 1


def test_duplicate_content_sources_keep_first_and_skip_the_rest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: Blizzard republishes identical maps across season folders.
    source_root = tmp_path / "Maps"
    _write_map(source_root / "Season1" / "same.w3x", b"identical-bytes")
    duplicate = _write_map(source_root / "Season9" / "same.w3x", b"identical-bytes")
    _write_map(source_root / "Season9" / "other.w3x", b"distinct-bytes")
    processed: list[str] = []
    monkeypatch.setattr(
        batch_runner, "build_map_load_context", lambda **_kwargs: MapLoadContext()
    )
    monkeypatch.setattr(
        batch_map_attempt,
        "fingerprint_dependencies",
        lambda source, *_args: source.sha256,
    )

    def process(
        index: int,
        fingerprint: SourceFingerprint,
        options: BatchOptions,
        context: MapLoadContext,
    ) -> MapBatchResult:
        processed.append(fingerprint.path)
        return _publish_fake_result(index, fingerprint, options, context)

    monkeypatch.setattr(batch_runner, "process_one_map", process)

    # When
    state = run_batch(BatchOptions(str(source_root), str(tmp_path / "output")))

    # Then: the duplicate never reaches the worker and the state stays unique.
    assert len(processed) == 2
    assert str(duplicate) not in processed
    assert len(state.results) == 2
    diagnostics_text = (tmp_path / "output" / "批量诊断.jsonl").read_text(
        encoding="utf-8"
    )
    assert diagnostics_text.count("duplicate_source_skipped") == 1
