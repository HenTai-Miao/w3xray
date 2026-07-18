"""Explicit trusted-description cache contracts for batch extraction."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Literal, assert_never

import pytest

from tests.batch_publication_fixture import (
    empty_result,
    publish_client_fill_result,
    publish_empty_result,
)
from tests.trusted_description_cache_fixture import published_cache
import w3xtool.batch_runner as batch_runner
import w3xtool.batch_map_attempt as batch_map_attempt
from w3xtool.batch_configuration import BatchConfigurationError
from w3xtool.batch_models import MapBatchResult, MapBatchState, SourceFingerprint
from w3xtool.batch_resume import load_previous_state
from w3xtool.batch_runner import BatchOptions, run_batch
from w3xtool.load_context import MapLoadContext
from w3xtool.trusted_description_cache import load_trusted_description_cache


type InvalidCacheKind = Literal["missing", "unowned", "symlink"]


def test_schema_one_root_state_is_not_reused(tmp_path: Path) -> None:
    # Given
    (tmp_path / "批量提取状态.json").write_text(
        '{"schema_version": 1, "results": []}\n',
        encoding="utf-8",
    )

    # When
    previous = load_previous_state(str(tmp_path))

    # Then
    assert previous.state is None
    assert tuple(item.code for item in previous.diagnostics) == (
        "legacy_state_ignored",
    )


def test_no_cache_run_stays_empty_when_output_has_description_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the output contains harvestable rows, but no explicit cache was selected.
    source_root = _maps(tmp_path)
    output = tmp_path / "output"
    _ = publish_client_fill_result(
        1,
        SourceFingerprint("/maps/old.w3x", 3, 4, "a" * 64),
        str(output),
    )
    seen_cache_sizes: list[int] = []
    _patch_batch(monkeypatch, seen_cache_sizes)

    # When
    _ = run_batch(BatchOptions(str(source_root), str(output)))

    # Then: active output rows never become trusted inputs for the same pipeline.
    assert seen_cache_sizes == [0]


def test_explicit_owned_cache_is_loaded_without_mutating_its_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a separately published owned cache and two consecutive batch runs.
    source_root = _maps(tmp_path)
    output = tmp_path / "output"
    cache_root = published_cache(tmp_path / "cache-fixture")
    before = _tree_snapshot(cache_root)
    seen_cache_sizes: list[int] = []
    seen_cache_identities: list[str] = []
    _patch_batch(monkeypatch, seen_cache_sizes, seen_cache_identities)
    options = BatchOptions(
        str(source_root),
        str(output),
        description_cache_path=str(cache_root),
    )

    # When
    _ = run_batch(options)
    _ = run_batch(options)

    # Then
    assert seen_cache_sizes == [1]
    assert seen_cache_identities == [
        load_trusted_description_cache(cache_root).manifest_sha256
    ]
    assert _tree_snapshot(cache_root) == before


def test_no_retry_failed_reprocesses_when_description_cache_manifest_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the same source first fails while bound to cache A.
    source_root = _maps(tmp_path)
    output = tmp_path / "output"
    cache_a = published_cache(tmp_path / "cache-a", raw="first")
    cache_b = published_cache(tmp_path / "cache-b", raw="second")
    cache_b_identity = load_trusted_description_cache(cache_b).manifest_sha256
    calls = 0
    monkeypatch.setattr(
        batch_map_attempt,
        "fingerprint_dependencies",
        lambda _source, _options, cache_identity: cache_identity,
    )
    monkeypatch.setattr(
        batch_runner,
        "build_map_load_context",
        lambda **_kwargs: MapLoadContext(),
    )

    def fail(
        _index: int,
        fingerprint: SourceFingerprint,
        _options: BatchOptions,
        context: MapLoadContext,
    ) -> MapBatchResult:
        nonlocal calls
        calls += 1
        return replace(
            empty_result(fingerprint, "unused"),
            output_directory="",
            stage="load/process",
            state=MapBatchState.FAILED,
            first_error="broken",
            dependency_fingerprint=context.description_cache_manifest_sha256,
        )

    monkeypatch.setattr(batch_runner, "process_one_map", fail)
    first_options = BatchOptions(
        str(source_root),
        str(output),
        retry_failed=False,
        description_cache_path=str(cache_a),
    )
    _ = run_batch(first_options)

    # When: cache B becomes the explicit input while failed retries stay disabled.
    second = run_batch(replace(first_options, description_cache_path=str(cache_b)))

    # Then: the failure from cache A is not reused beside cache B's snapshot.
    assert calls == 2
    assert second.results[0].dependency_fingerprint == cache_b_identity


@pytest.mark.parametrize("kind", ("missing", "unowned", "symlink"))
def test_batch_preflight_rejects_an_invalid_explicit_cache(
    tmp_path: Path,
    kind: InvalidCacheKind,
) -> None:
    # Given: missing, unowned, and symlinked roots all fail closed.
    selected = tmp_path / "not-owned"
    match kind:
        case "missing":
            selected = tmp_path / "missing"
        case "unowned":
            selected.mkdir()
        case "symlink":
            target = tmp_path / "target"
            target.mkdir()
            selected.symlink_to(target, target_is_directory=True)
        case unreachable:
            assert_never(unreachable)
    options = BatchOptions(
        source_directory=str(_maps(tmp_path)),
        output_root=str(tmp_path / "output"),
        description_cache_path=str(selected),
    )

    # When / Then
    with pytest.raises(BatchConfigurationError, match="description cache"):
        run_batch(options)


@pytest.mark.parametrize("overlap", ("source", "output"))
def test_batch_preflight_rejects_cache_overlap(
    tmp_path: Path,
    overlap: str,
) -> None:
    # Given
    source_root = _maps(tmp_path)
    output = tmp_path / "output"
    selected = source_root if overlap == "source" else output
    options = BatchOptions(
        str(source_root),
        str(output),
        description_cache_path=str(selected),
    )

    # When / Then
    with pytest.raises(BatchConfigurationError, match="description cache"):
        run_batch(options)


def _maps(tmp_path: Path) -> Path:
    root = tmp_path / "Maps"
    root.mkdir(exist_ok=True)
    (root / "sample.w3x").write_bytes(b"map")
    return root


def _patch_batch(
    monkeypatch: pytest.MonkeyPatch,
    seen_cache_sizes: list[int],
    seen_cache_identities: list[str] | None = None,
) -> None:
    monkeypatch.setattr(
        batch_map_attempt,
        "fingerprint_dependencies",
        lambda source, *_args: source.sha256,
    )
    monkeypatch.setattr(
        batch_runner,
        "build_map_load_context",
        lambda **_kwargs: MapLoadContext(),
    )

    def process(
        index: int,
        fingerprint: SourceFingerprint,
        options: BatchOptions,
        context: MapLoadContext,
    ) -> MapBatchResult:
        seen_cache_sizes.append(len(context.description_cache.entries))
        if seen_cache_identities is not None:
            seen_cache_identities.append(context.description_cache_manifest_sha256)
        return publish_empty_result(index, fingerprint, options.output_root)

    monkeypatch.setattr(batch_runner, "process_one_map", process)


def _tree_snapshot(root: Path) -> dict[str, tuple[bytes, int]]:
    return {
        path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in sorted(root.iterdir())
        if path.is_file()
    }
