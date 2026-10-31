"""Batch failure cleanup must retain directories that replace an owned stage."""

from __future__ import annotations

from pathlib import Path
from dataclasses import replace
import json

import pytest

import gametool.batch_global_publication as global_publication
import gametool.batch_stage_cleanup as stage_cleanup
import gametool.batch_publication_record as publication_record
from gametool.batch_map_publication import create_map_stage, discard_map_stage
from gametool.batch_models import BATCH_SCHEMA_VERSION, BatchState
from gametool.batch_publication_recovery import recover_map_publications
from gametool.batch_publication_record import (
    load_transaction,
    record_path,
    write_transaction,
)
from gametool.batch_publication_resolution import keep_previous_destination
from gametool.description_cache import format_description_cache_tsv
from gametool.description_cache_models import EMPTY_DESCRIPTION_CACHE


def test_global_stage_cleanup_preserves_a_replacement_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    retained = tmp_path / "retained-stage"
    replacement: Path | None = None
    write_text = global_publication._write_text

    def replace_stage(root: Path, name: str, text: str) -> None:
        nonlocal replacement
        write_text(root, name, text)
        root.rename(retained)
        root.mkdir()
        replacement = root / "user-data.txt"
        replacement.write_bytes(b"concurrent data")
        raise OSError("injected publication failure")

    monkeypatch.setattr(global_publication, "_write_text", replace_stage)

    with pytest.raises(OSError, match="injected publication failure"):
        global_publication.publish_global_generation(
            tmp_path,
            BatchState(BATCH_SCHEMA_VERSION, ()),
            format_description_cache_tsv(EMPTY_DESCRIPTION_CACHE),
            "",
        )

    assert replacement is not None
    assert replacement.read_bytes() == b"concurrent data"
    assert tuple(retained.iterdir())


def test_map_stage_cleanup_preserves_a_replacement_directory(tmp_path: Path) -> None:
    publication = create_map_stage(str(tmp_path), "地图/001_map_aaaaaaaa", "a" * 64)
    original = publication.stage
    retained = tmp_path / "retained-stage"
    (original / "partial-report.txt").write_bytes(b"owned evidence")
    original.rename(retained)
    original.mkdir()
    replacement = original / "user-data.txt"
    replacement.write_bytes(b"concurrent data")

    diagnostics = discard_map_stage(publication, str(tmp_path))

    assert replacement.read_bytes() == b"concurrent data"
    assert (retained / "partial-report.txt").read_bytes() == b"owned evidence"
    assert any(item.code == "unproved_path" for item in diagnostics), diagnostics


def test_stage_cleanup_removes_nested_owned_payloads_and_record(tmp_path: Path) -> None:
    publication = create_map_stage(str(tmp_path), "地图/001_map_aaaaaaaa", "a" * 64)
    nested = publication.stage / "icons" / "nested"
    nested.mkdir(parents=True)
    (nested / "payload.blp").write_bytes(b"owned")
    (publication.stage / "report.tsv").write_bytes(b"owned report")

    assert discard_map_stage(publication, str(tmp_path)) == ()
    assert not publication.stage.exists()
    assert not record_path(tmp_path / "地图", publication.transaction_id).exists()


def test_legacy_building_transaction_retains_unproved_directory(tmp_path: Path) -> None:
    publication = create_map_stage(str(tmp_path), "地图/001_map_aaaaaaaa", "a" * 64)
    maps_root = tmp_path / "地图"
    record = record_path(maps_root, publication.transaction_id)
    legacy = replace(load_transaction(record), stage_identity=None)
    write_transaction(maps_root, legacy)
    payload = publication.stage / "existing.bin"
    payload.write_bytes(b"unproved legacy data")

    diagnostics = recover_map_publications(str(tmp_path))

    assert payload.read_bytes() == b"unproved legacy data"
    assert record.is_file()
    assert "stage_identity" not in json.loads(record.read_text(encoding="utf-8"))
    assert any(item.code == "unproved_path" for item in diagnostics)


def test_child_replacement_after_inventory_is_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    publication = create_map_stage(str(tmp_path), "地图/001_map_aaaaaaaa", "a" * 64)
    child = publication.stage / "report.tsv"
    child.write_bytes(b"owned report")
    retained = publication.stage / "retained.tsv"
    children = stage_cleanup._children

    def replace_after_inventory(path: Path):
        entries = children(path)
        with pytest.raises(OSError):
            child.rename(retained)
        return entries

    monkeypatch.setattr(stage_cleanup, "_children", replace_after_inventory)

    diagnostics = discard_map_stage(publication, str(tmp_path))

    assert diagnostics == ()
    assert not publication.stage.exists()
    assert not retained.exists()


def test_stage_child_junction_is_retained_without_touching_target(
    tmp_path: Path,
) -> None:
    import _winapi

    publication = create_map_stage(str(tmp_path), "地图/001_map_aaaaaaaa", "a" * 64)
    external = tmp_path / "outside"
    external.mkdir()
    payload = external / "user-data.txt"
    payload.write_bytes(b"external data")
    junction = publication.stage / "redirected"
    _winapi.CreateJunction(str(external), str(junction))

    diagnostics = discard_map_stage(publication, str(tmp_path))

    assert payload.read_bytes() == b"external data"
    assert junction.is_junction()
    assert any(item.code == "unproved_path" for item in diagnostics)


def test_stage_creation_never_adopts_an_existing_directory(tmp_path: Path) -> None:
    path = tmp_path / "stage"
    path.mkdir()
    payload = path / "user-data.txt"
    payload.write_bytes(b"existing data")

    with pytest.raises(FileExistsError):
        stage_cleanup.create_owned_stage(path)

    assert payload.read_bytes() == b"existing data"


def test_missing_owned_stage_drops_only_its_record(tmp_path: Path) -> None:
    publication = create_map_stage(str(tmp_path), "地图/001_map_aaaaaaaa", "a" * 64)
    publication.stage.rmdir()

    assert discard_map_stage(publication, str(tmp_path)) == ()
    assert not record_path(tmp_path / "地图", publication.transaction_id).exists()


def test_deletion_failure_preserves_stage_and_releases_held_handles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    publication = create_map_stage(str(tmp_path), "地图/001_map_aaaaaaaa", "a" * 64)
    nested = publication.stage / "nested"
    nested.mkdir()
    payload = nested / "report.tsv"
    payload.write_bytes(b"owned report")

    def fail_delete(self, handle: int) -> None:
        raise OSError("injected disposition failure")

    monkeypatch.setattr(stage_cleanup._CleanupApi, "delete", fail_delete)

    diagnostics = discard_map_stage(publication, str(tmp_path))

    assert payload.read_bytes() == b"owned report"
    assert any("injected disposition failure" in item.detail for item in diagnostics)
    publication.stage.rename(tmp_path / "retained-stage")


def test_cleanup_holds_directory_identity_until_disposition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    publication = create_map_stage(str(tmp_path), "地图/001_map_aaaaaaaa", "a" * 64)
    children = stage_cleanup._children
    denied: list[bool] = []

    def attempt_replacement(path: Path):
        with pytest.raises(OSError):
            publication.stage.rename(tmp_path / "concurrent-stage")
        denied.append(True)
        return children(path)

    monkeypatch.setattr(stage_cleanup, "_children", attempt_replacement)

    assert discard_map_stage(publication, str(tmp_path)) == ()
    assert denied == [True]


def test_cleanup_reports_primary_and_handle_release_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    publication = create_map_stage(str(tmp_path), "地图/001_map_aaaaaaaa", "a" * 64)
    child = publication.stage / "report.tsv"
    child.write_bytes(b"retained evidence")
    close = stage_cleanup._CleanupApi.close
    closed: list[int] = []

    def fail_delete(self, handle: int) -> None:
        raise OSError("original disposition failure")

    def fail_close(self, handle: int) -> None:
        assert handle not in closed
        closed.append(handle)
        close(self, handle)
        raise OSError("injected handle release failure")

    monkeypatch.setattr(stage_cleanup._CleanupApi, "delete", fail_delete)
    monkeypatch.setattr(stage_cleanup._CleanupApi, "close", fail_close)

    diagnostics = discard_map_stage(publication, str(tmp_path))

    assert child.read_bytes() == b"retained evidence"
    assert len(closed) == 2
    assert any("original disposition failure" in item.detail for item in diagnostics)
    assert any("injected handle release failure" in item.detail for item in diagnostics)
    publication.stage.rename(tmp_path / "retained-stage")


@pytest.mark.parametrize("legacy", (False, True))
def test_prepared_cleanup_requires_recorded_stage_identity(
    tmp_path: Path, legacy: bool
) -> None:
    publication = create_map_stage(str(tmp_path), "地图/001_map_aaaaaaaa", "a" * 64)
    maps_root = tmp_path / "地图"
    transaction = load_transaction(record_path(maps_root, publication.transaction_id))
    if legacy:
        transaction = replace(transaction, stage_identity=None)
        write_transaction(maps_root, transaction)
    payload = publication.stage / "data.tsv"
    payload.write_bytes(b"retained legacy or replacement")
    if not legacy:
        publication.stage.rename(tmp_path / "original")
        publication.stage.mkdir()
        payload.write_bytes(b"retained legacy or replacement")

    diagnostics = keep_previous_destination(maps_root, transaction, True, False)

    assert payload.read_bytes() == b"retained legacy or replacement"
    assert record_path(maps_root, publication.transaction_id).exists()
    assert any(item.code == "unproved_path" for item in diagnostics)


@pytest.mark.parametrize("legacy", (False, True))
def test_backup_cleanup_requires_recorded_directory_identity(
    tmp_path: Path, legacy: bool
) -> None:
    publication = create_map_stage(str(tmp_path), "地图/001_map_aaaaaaaa", "a" * 64)
    maps_root = tmp_path / "地图"
    transaction = load_transaction(record_path(maps_root, publication.transaction_id))
    backup = maps_root / transaction.backup_name
    identity = stage_cleanup.create_owned_stage(backup)
    transaction = replace(transaction, backup_identity=None if legacy else identity)
    write_transaction(maps_root, transaction)
    if not legacy:
        backup.rename(tmp_path / "original-backup")
        backup.mkdir()
    payload = backup / "user-data.tsv"
    payload.write_bytes(b"retained legacy or replacement")

    diagnostics = keep_previous_destination(maps_root, transaction, True, True)

    assert payload.read_bytes() == b"retained legacy or replacement"
    assert record_path(maps_root, publication.transaction_id).exists()
    assert any(item.code == "unproved_path" for item in diagnostics)


@pytest.mark.parametrize("replace_file", (False, True))
def test_transaction_cleanup_preserves_changed_record_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, replace_file: bool
) -> None:
    publication = create_map_stage(str(tmp_path), "地图/001_map_aaaaaaaa", "a" * 64)
    maps_root = tmp_path / "地图"
    record = record_path(maps_root, publication.transaction_id)
    transaction = load_transaction(record)
    original = record.read_bytes()
    retained = maps_root / "original-journal.json"
    reader = publication_record.read_bounded_regular_file

    def change_after_read(path: Path, max_bytes=None):
        result = reader(path, max_bytes)
        if replace_file:
            record.rename(retained)
        record.write_bytes(b"foreign journal bytes")
        return result

    monkeypatch.setattr(
        publication_record, "read_bounded_regular_file", change_after_read
    )

    with pytest.raises(OSError, match="transaction record retained"):
        publication_record.remove_transaction(maps_root, transaction)

    assert record.read_bytes() == b"foreign journal bytes"
    if replace_file:
        assert retained.read_bytes() == original


def test_transaction_cleanup_reports_invalid_utf8_as_record_error(
    tmp_path: Path,
) -> None:
    publication = create_map_stage(str(tmp_path), "地图/001_map_aaaaaaaa", "a" * 64)
    maps_root = tmp_path / "地图"
    record = record_path(maps_root, publication.transaction_id)
    transaction = load_transaction(record)
    record.write_bytes(b"\xff\xfeinvalid record")

    with pytest.raises(publication_record.PublicationRecordError, match="not UTF-8"):
        publication_record.remove_transaction(maps_root, transaction)

    assert record.read_bytes() == b"\xff\xfeinvalid record"
    assert any(
        item.code == "invalid_transaction"
        for item in recover_map_publications(str(tmp_path))
    )
