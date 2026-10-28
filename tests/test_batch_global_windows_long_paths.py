"""Global publication keeps native long I/O separate from logical identities."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from gametool.acceptance_batch import check_batch_publication
import gametool.batch_global_publication as publication
import gametool.batch_map_publication as map_publication
from gametool.batch_global_models import GLOBAL_MANIFEST_NAME, GLOBAL_PAYLOAD_NAMES
from gametool.batch_models import BATCH_SCHEMA_VERSION, BatchState
from gametool.batch_publication_record import (
    load_transaction,
    record_path,
    write_transaction,
)
from gametool.description_cache import format_description_cache_tsv
from gametool.description_cache_models import EMPTY_DESCRIPTION_CACHE
from gametool.windows_output_paths import native_output_path


def _io(path: Path) -> Path:
    return Path(native_output_path(str(path.absolute())))


def _long_root(tmp_path: Path, minimum: int = 193) -> Path:
    # The observed Windows output has 193 characters; its generated stage has
    # 266, beyond both CreateDirectory's reserve and ordinary MoveFileEx paths.
    padding = max(1, minimum - len(str(tmp_path)) - 1)
    output = tmp_path / ("o" * padding)
    assert len(str(output)) >= minimum
    return output


def _cache_text() -> str:
    return format_description_cache_tsv(EMPTY_DESCRIPTION_CACHE)


def _stage_names(output: Path) -> tuple[str, ...]:
    return tuple(
        path.name
        for path in _io(output / ".gamexray-global").iterdir()
        if path.name.startswith(".gamexray-global-stage-")
    )


def _generation_bytes(directory: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in _io(directory).iterdir()}


def test_long_generation_publishes_loads_and_replaces_without_logical_prefix(
    tmp_path: Path,
) -> None:
    output = _long_root(tmp_path)
    state = BatchState(BATCH_SCHEMA_VERSION, ())
    first = publication.publish_global_generation(
        output, state, _cache_text(), '{"phase":"first"}\n'
    )
    assert (
        len(str(output / ".gamexray-global" / (".gamexray-global-stage-" + "a" * 32)))
        >= 266
    )
    assert (
        first.directory
        == output / ".gamexray-global" / "generations" / first.generation_id
    )
    assert not str(first.directory).startswith("\\\\?\\")
    assert publication.load_current_generation(output) == first
    old_bytes = _generation_bytes(first.directory)
    assert set(old_bytes) == {*GLOBAL_PAYLOAD_NAMES, GLOBAL_MANIFEST_NAME}

    second = publication.publish_global_generation(
        output, state, _cache_text(), '{"phase":"second"}\n'
    )

    assert second.generation_id != first.generation_id
    assert publication.load_current_generation(output) == second
    assert publication.load_current_batch_state(output) == state
    assert (
        second.directory
        == output / ".gamexray-global" / "generations" / second.generation_id
    )
    assert _generation_bytes(first.directory) == old_bytes
    new_bytes = _generation_bytes(second.directory)
    manifest = json.loads(new_bytes[GLOBAL_MANIFEST_NAME])
    assert manifest["artifact_count"] == len(GLOBAL_PAYLOAD_NAMES)
    for artifact in manifest["artifacts"]:
        payload = new_bytes[artifact["name"]]
        assert len(payload) == artifact["size"]
        assert hashlib.sha256(payload).hexdigest() == artifact["sha256"]
    assert second.diagnostics_text == '{"phase":"second"}\n'
    assert _stage_names(output) == ()


def test_long_failed_stage_cleans_owned_payloads_and_preserves_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = _long_root(tmp_path)
    state = BatchState(BATCH_SCHEMA_VERSION, ())
    first = publication.publish_global_generation(output, state, _cache_text(), "")
    old_bytes = _generation_bytes(first.directory)
    write_text = publication._write_text
    attempted: list[Path] = []

    def fail_manifest(root: Path, name: str, text: str) -> None:
        if (
            root.name.startswith(".gamexray-global-stage-")
            and name == GLOBAL_MANIFEST_NAME
        ):
            attempted.append(root)
            assert len(_generation_bytes(root)) == len(GLOBAL_PAYLOAD_NAMES)
            raise OSError("injected long stage manifest failure")
        write_text(root, name, text)

    monkeypatch.setattr(publication, "_write_text", fail_manifest)
    with pytest.raises(OSError, match="injected long stage manifest failure"):
        publication.publish_global_generation(output, state, _cache_text(), "")

    assert len(attempted) == 1 and len(str(attempted[0])) >= 266
    assert not _io(attempted[0]).exists()
    assert _stage_names(output) == ()
    assert publication.load_current_generation(output) == first
    assert _generation_bytes(first.directory) == old_bytes


def test_long_batch_acceptance_publishes_and_strictly_reuses_real_fixture(
    tmp_path: Path,
) -> None:
    fixture = Path(__file__).parent / "fixtures/maps/war3net-map-script-builder.w3x"
    before = (fixture.read_bytes(), fixture.stat().st_ino, fixture.stat().st_mtime_ns)
    # acceptance_batch appends batch-publication/output, keeping the exact
    # original output depth instead of shortening its actual transaction paths.
    evidence = _long_root(tmp_path, 193 - len("/batch-publication/output"))

    result = check_batch_publication(fixture, evidence)

    assert "first=processed; second=reused; leftovers=0" in result
    assert "manifest_sha256=" in result
    assert before == (
        fixture.read_bytes(),
        fixture.stat().st_ino,
        fixture.stat().st_mtime_ns,
    )
    output = evidence / "batch-publication" / "output"
    assert len(str(output)) >= 193
    assert publication.load_current_generation(output) is not None
    assert _stage_names(output) == ()


def test_long_map_build_discards_only_matching_transaction(tmp_path: Path) -> None:
    output = _long_root(tmp_path)
    stage = map_publication.create_map_stage(
        str(output), "地图/001_example_aaaaaaaa", "a" * 64
    )
    record = record_path(output / "地图", stage.transaction_id)
    assert len(str(stage.stage)) >= 248 and len(str(record)) >= 260
    assert not str(stage.stage).startswith("\\\\?\\")
    _io(stage.stage / "完整字段.tsv").write_bytes(b"complete owned bytes")

    assert map_publication.discard_map_stage(stage, str(output)) == ()

    assert not _io(stage.stage).exists()
    assert not _io(record).exists()


def test_long_map_build_preserves_mismatched_transaction(tmp_path: Path) -> None:
    output = _long_root(tmp_path)
    stage = map_publication.create_map_stage(
        str(output), "地图/001_example_aaaaaaaa", "a" * 64
    )
    maps_root = output / "地图"
    record = record_path(maps_root, stage.transaction_id)
    transaction = load_transaction(_io(record))
    replacement = replace(transaction, source_sha256="b" * 64)
    write_transaction(_io(maps_root), replacement)
    payload = stage.stage / "必须保留.tsv"
    _io(payload).write_bytes(b"not proved to belong to the supplied stage")
    before = _io(record).read_bytes()

    diagnostics = map_publication.discard_map_stage(stage, str(output))

    assert tuple(row.code for row in diagnostics) == ("unproved_path",)
    assert _io(payload).read_bytes() == b"not proved to belong to the supplied stage"
    assert _io(record).read_bytes() == before
