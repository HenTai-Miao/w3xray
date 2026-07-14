"""Sequential batch orchestration and resume tests."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

import w3xtool.batch_runner as batch_runner
from w3xtool.batch_models import MapBatchResult, MapBatchState, SourceFingerprint
from w3xtool.batch_runner import (
    BatchConfigurationError,
    BatchOptions,
    OWNERSHIP_MARKER,
    REQUIRED_MAP_REPORTS,
    run_batch,
)
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
    )


def _publish_fake_result(
    index: int,
    fingerprint: SourceFingerprint,
    options: BatchOptions,
    _context: MapLoadContext,
) -> MapBatchResult:
    relative = f"地图/{index:03d}_{fingerprint.sha256[:8]}"
    destination = Path(options.output_root, relative)
    destination.mkdir(parents=True)
    for name in REQUIRED_MAP_REPORTS:
        (destination / name).write_text("ok\n", encoding="utf-8")
    (destination / OWNERSHIP_MARKER).write_text(fingerprint.sha256, encoding="ascii")
    return _result(fingerprint, output_directory=relative)


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


def test_resume_reprocesses_when_v2_reports_are_missing(tmp_path: Path) -> None:
    # Given: a schema-v1-era result directory has every legacy report.
    fingerprint = SourceFingerprint("/maps/sample.w3x", 3, 4, "a" * 64)
    relative = "地图/001_sample_aaaaaaaa"
    destination = tmp_path / relative
    destination.mkdir(parents=True)
    for name in (
        "地图摘要.txt",
        "图标索引.tsv",
        "对象描述.tsv",
        "图标完整性.txt",
        "描述完整性.txt",
    ):
        (destination / name).write_text("legacy\n", encoding="utf-8")
    (destination / OWNERSHIP_MARKER).write_text("a" * 64, encoding="ascii")
    result = _result(fingerprint, output_directory=relative)

    # When
    reusable = batch_runner._published_result_exists(str(tmp_path), result)

    # Then: complete text and relation reports are mandatory for schema v2.
    assert not reusable
