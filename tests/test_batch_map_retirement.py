"""Completed-batch retirement coverage for superseded map directories."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from tests.batch_publication_fixture import empty_result, write_empty_publication
import gametool.batch_map_attempt as batch_map_attempt
import gametool.batch_map_retirement as batch_map_retirement
import gametool.batch_runner as batch_runner
from gametool.batch_configuration import BatchOptions
from gametool.batch_manifest_models import PublicationValidation
from gametool.batch_models import (
    BATCH_SCHEMA_VERSION,
    BatchState,
    MapBatchResult,
    MapBatchState,
    SourceFingerprint,
)
from gametool.batch_status import PublicationResult
from gametool.load_context import MapLoadContext


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


def test_windows_retirement_without_directory_anchor_preserves_all_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace
    from typing import cast

    from gametool.batch_global_models import GlobalGeneration
    from gametool.batch_output_lock import BatchOutputLease

    output = tmp_path / "output"
    maps_root = output / "地图"
    original = maps_root / "previous"
    original.mkdir(parents=True)
    evidence = original / "sentinel"
    evidence.write_bytes(b"preserve every owned and foreign name")
    before = (evidence.read_bytes(), evidence.stat().st_ino)
    state = BatchState(BATCH_SCHEMA_VERSION, ())
    generation = cast(GlobalGeneration, cast(object, SimpleNamespace(state=state)))
    lease = cast(BatchOutputLease, object())
    opened: list[Path] = []
    monkeypatch.setattr(batch_map_retirement, "lease_is_current", lambda *_: True)
    monkeypatch.setattr(
        batch_map_retirement, "load_current_generation", lambda *_: generation
    )
    monkeypatch.setattr(
        batch_map_retirement,
        "open_maps_root",
        lambda path: opened.append(path),
    )

    def forbidden_scan(*_args: object):
        raise AssertionError(
            "missing directory anchor must forbid scanning or deletion"
        )

    monkeypatch.setattr(batch_map_retirement, "_retire_from_maps_root", forbidden_scan)
    assert (
        batch_map_retirement.retire_superseded_map_publications(
            str(output), state, lease
        )
        == ()
    )
    assert opened == [maps_root]
    assert (evidence.read_bytes(), evidence.stat().st_ino) == before
    assert tuple(maps_root.iterdir()) == (original,)
