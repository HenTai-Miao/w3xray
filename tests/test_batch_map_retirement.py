"""Completed-batch retirement coverage for superseded map directories."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import os
from pathlib import Path

import pytest

from tests.batch_publication_fixture import empty_result, write_empty_publication
import w3xtool.batch_map_attempt as batch_map_attempt
import w3xtool.batch_map_retirement as batch_map_retirement
import w3xtool.batch_runner as batch_runner
from w3xtool.batch_configuration import BatchOptions
from w3xtool.batch_manifest_models import PublicationValidation
from w3xtool.batch_models import (
    BATCH_SCHEMA_VERSION,
    BatchState,
    MapBatchResult,
    MapBatchState,
    SourceFingerprint,
)
from w3xtool.batch_status import PublicationResult
from w3xtool.load_context import MapLoadContext


def _publish_named_result(
    fingerprint: SourceFingerprint,
    options: BatchOptions,
    *,
    relative: str,
    dependency: str,
    transaction: int,
) -> MapBatchResult:
    destination = Path(options.output_root, relative)
    destination.mkdir(parents=True, exist_ok=True)
    result = replace(
        empty_result(fingerprint, relative),
        dependency_fingerprint=dependency,
    )
    return write_empty_publication(destination, result, f"{transaction:032x}")


def _write_map(path: Path, payload: bytes = b"map") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _configure_direct_batch(
    monkeypatch: pytest.MonkeyPatch,
    dependency: list[str],
) -> None:
    monkeypatch.setattr(
        batch_runner,
        "build_map_load_context",
        lambda **_kwargs: MapLoadContext(),
    )
    monkeypatch.setattr(
        batch_map_attempt,
        "fingerprint_dependencies",
        lambda *_args: dependency[0],
    )


def test_completed_batch_retires_owned_old_display_name_for_same_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: two successful generations publish one source under different names.
    source_root = tmp_path / "Maps"
    _write_map(source_root / "sample.w3x")
    output = tmp_path / "output"
    options = BatchOptions(str(source_root), str(output))
    dependency = ["1" * 64]
    relative = ["地图/001_old-name_deadbeef"]
    transaction = [1]
    _configure_direct_batch(monkeypatch, dependency)

    def process(
        _index: int,
        fingerprint: SourceFingerprint,
        current: BatchOptions,
        _context: MapLoadContext,
    ) -> MapBatchResult:
        return _publish_named_result(
            fingerprint,
            current,
            relative=relative[0],
            dependency=dependency[0],
            transaction=transaction[0],
        )

    monkeypatch.setattr(batch_runner, "process_one_map", process)
    _ = batch_runner.run_batch(options)
    old_directory = output / relative[0]
    dependency[0] = "2" * 64
    relative[0] = "地图/001_新显示名_deadbeef"
    transaction[0] = 2

    # When: the replacement batch reaches its final authoritative checkpoint.
    state = batch_runner.run_batch(options)

    # Then: only the current destination remains for that source.
    assert not old_directory.exists()
    assert state.results[0].output_directory == relative[0]
    assert (output / relative[0]).is_dir()


def test_retirement_preserves_unproved_foreign_and_current_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: one superseded directory sits beside unowned and foreign evidence.
    source_root = tmp_path / "Maps"
    _write_map(source_root / "sample.w3x")
    output = tmp_path / "output"
    options = BatchOptions(str(source_root), str(output))
    dependency = ["3" * 64]
    relative = ["地图/001_old-name_cafebabe"]
    transaction = [3]
    _configure_direct_batch(monkeypatch, dependency)

    def process(
        _index: int,
        fingerprint: SourceFingerprint,
        current: BatchOptions,
        _context: MapLoadContext,
    ) -> MapBatchResult:
        return _publish_named_result(
            fingerprint,
            current,
            relative=relative[0],
            dependency=dependency[0],
            transaction=transaction[0],
        )

    monkeypatch.setattr(batch_runner, "process_one_map", process)
    _ = batch_runner.run_batch(options)
    old_directory = output / relative[0]
    unowned = output / "地图" / "unowned"
    unowned.mkdir()
    (unowned / ".w3xray-batch-owned").write_text(
        hashlib.sha256(b"map").hexdigest(),
        encoding="ascii",
    )
    foreign_source = SourceFingerprint(
        str(tmp_path / "foreign.w3x"),
        7,
        1,
        hashlib.sha256(b"foreign").hexdigest(),
    )
    foreign_relative = "地图/foreign-owned"
    foreign_result = replace(
        empty_result(foreign_source, foreign_relative),
        dependency_fingerprint="4" * 64,
    )
    foreign = output / foreign_relative
    foreign.mkdir()
    _ = write_empty_publication(foreign, foreign_result, f"{4:032x}")
    dependency[0] = "5" * 64
    relative[0] = "地图/001_current-name_cafebabe"
    transaction[0] = 5

    # When: the full replacement batch completes.
    state = batch_runner.run_batch(options)

    # Then: only the proven same-source predecessor is retired.
    assert not old_directory.exists()
    assert unowned.is_dir()
    assert foreign.is_dir()
    assert (output / state.results[0].output_directory).is_dir()


@pytest.mark.skipif(os.name == "nt", reason="symlink creation is not portable on CI")
def test_retirement_never_follows_a_map_root_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a current batch and an external valid directory linked below 地图/.
    source_root = tmp_path / "Maps"
    _write_map(source_root / "sample.w3x")
    output = tmp_path / "output"
    options = BatchOptions(str(source_root), str(output))
    dependency = ["6" * 64]
    relative = ["地图/001_current_abcd1234"]
    _configure_direct_batch(monkeypatch, dependency)

    def process(
        _index: int,
        fingerprint: SourceFingerprint,
        current: BatchOptions,
        _context: MapLoadContext,
    ) -> MapBatchResult:
        return _publish_named_result(
            fingerprint,
            current,
            relative=relative[0],
            dependency=dependency[0],
            transaction=6,
        )

    monkeypatch.setattr(batch_runner, "process_one_map", process)
    state = batch_runner.run_batch(options)
    external = tmp_path / "external-owned"
    external.mkdir()
    external_result = replace(
        empty_result(state.results[0].source, "地图/external-owned"),
        dependency_fingerprint="7" * 64,
    )
    _ = write_empty_publication(external, external_result, f"{7:032x}")
    linked = output / "地图" / "linked-old"
    linked.symlink_to(external, target_is_directory=True)

    # When: a complete reused batch runs retirement.
    _ = batch_runner.run_batch(options)

    # Then: the link and its external target remain untouched.
    assert linked.is_symlink()
    assert external.is_dir()


def test_retirement_authority_rejects_legacy_partial_failed_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a legacy partial state whose authoritative publication axis failed.
    source = SourceFingerprint("/maps/failed.w3x", 3, 4, "a" * 64)
    result = replace(
        empty_result(source, "地图/001_failed_aaaaaaaa"),
        state=MapBatchState.PARTIAL,
        publication_result=PublicationResult.FAILED,
    )
    maps_root = tmp_path / "地图"
    destination = maps_root / "001_failed_aaaaaaaa"
    destination.mkdir(parents=True)
    monkeypatch.setattr(
        batch_map_retirement,
        "verify_map_publication",
        lambda *_args: PublicationValidation(True, "valid"),
    )

    # When: retirement derives its authority from the global state.
    authority = batch_map_retirement._authority(
        BatchState(BATCH_SCHEMA_VERSION, (result,)), maps_root
    )

    # Then: publication failure prevents any directory from becoming authority.
    assert authority is None
