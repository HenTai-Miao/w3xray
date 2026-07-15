"""Crash recovery coverage for per-map directory publication transactions."""

from __future__ import annotations

import errno
import json
from pathlib import Path
from typing import Callable

import pytest

from tests.batch_publication_fixture import (
    empty_result,
    publish_empty_result,
    write_empty_publication,
)
import w3xtool.batch_map_publication as publication_module
from w3xtool.batch_manifest_validation import verify_map_publication
from w3xtool.batch_models import SourceFingerprint


_DIGEST = "a" * 64
_OLD_TRANSACTION = "a" * 32
_NEW_TRANSACTION = "b" * 32
_RELATIVE = "地图/001_aaaaaaaa"


def test_create_map_stage_persists_a_building_transaction(tmp_path: Path) -> None:
    # Given / When: a stage is allocated for one exact destination and source.
    staged = publication_module.create_map_stage(
        str(tmp_path),
        _RELATIVE,
        _DIGEST,
        transaction_id=_NEW_TRANSACTION,
    )

    # Then: the typed stage and durable record bind the private names.
    record = tmp_path / "地图" / f".w3xray-map-transaction-{_NEW_TRANSACTION}.json"
    payload = json.loads(record.read_text(encoding="utf-8"))
    assert staged.stage.name == f".w3xray-map-stage-{_NEW_TRANSACTION}"
    assert staged.relative == _RELATIVE
    assert payload["phase"] == "building"
    assert payload["source_sha256"] == _DIGEST


@pytest.mark.parametrize(
    ("failure_phase", "failure_errno"),
    (
        ("backup", errno.EIO),
        ("destination", errno.EIO),
        ("destination", errno.ENOSPC),
        ("sync", errno.EIO),
        ("cleanup", errno.EIO),
    ),
)
def test_recovery_keeps_exactly_one_valid_generation_after_publication_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_phase: str,
    failure_errno: int,
) -> None:
    # Given: an old valid generation and a new manifest-valid private stage.
    fingerprint = _fingerprint()
    old = publish_empty_result(1, fingerprint, str(tmp_path))
    staged, new = _prepare_stage(tmp_path, fingerprint)
    restore = _inject_failure(monkeypatch, failure_phase, failure_errno)

    # When: publication is interrupted and startup recovery runs later.
    with pytest.raises(OSError):
        publication_module.publish_map_stage(
            staged,
            str(tmp_path),
            new.manifest_sha256,
        )
    restore()
    diagnostics = publication_module.recover_map_publications(str(tmp_path))

    # Then: either proven generation survives, with no private leftovers.
    destination = tmp_path / _RELATIVE
    assert verify_map_publication(destination).valid
    assert verify_map_publication(destination).manifest_sha256 in {
        old.manifest_sha256,
        new.manifest_sha256,
    }
    assert not tuple((tmp_path / "地图").glob(".w3xray-map-*-*"))
    assert all(item.code != "unproved_path" for item in diagnostics)


def test_recovery_completes_a_valid_stage_when_destination_is_absent(
    tmp_path: Path,
) -> None:
    # Given: manifest finalization completed before the publisher was entered.
    staged, result = _prepare_stage(tmp_path, _fingerprint())

    # When: startup recovery observes the durable transaction.
    first = publication_module.recover_map_publications(str(tmp_path))
    second = publication_module.recover_map_publications(str(tmp_path))

    # Then: the stage is committed once and a second recovery is a no-op.
    destination = tmp_path / staged.relative
    validation = verify_map_publication(destination)
    assert validation.valid
    assert validation.manifest_sha256 == result.manifest_sha256
    assert tuple(item.code for item in first) == ("published_prepared_stage",)
    assert second == ()


def test_recovery_restores_owned_backup_when_new_stage_is_not_proven(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the old generation reached backup, then the new rename failed.
    fingerprint = _fingerprint()
    old = publish_empty_result(1, fingerprint, str(tmp_path))
    staged, new = _prepare_stage(tmp_path, fingerprint)
    restore = _inject_failure(monkeypatch, "destination", errno.EIO)
    with pytest.raises(OSError):
        publication_module.publish_map_stage(
            staged,
            str(tmp_path),
            new.manifest_sha256,
        )
    restore()
    (staged.stage / "地图摘要.txt").write_text("corrupt", encoding="utf-8")

    # When: recovery cannot prove the new stage but can prove the backup owner.
    diagnostics = publication_module.recover_map_publications(str(tmp_path))

    # Then: the old publication is restored without deleting the corrupt stage.
    destination = tmp_path / _RELATIVE
    assert verify_map_publication(destination).manifest_sha256 == old.manifest_sha256
    assert staged.stage.exists()
    assert any(item.code == "unproved_path" for item in diagnostics)


def test_recovery_leaves_unowned_private_names_and_invalid_record_untouched(
    tmp_path: Path,
) -> None:
    # Given: similarly named paths were not created by a valid transaction.
    maps_root = tmp_path / "地图"
    maps_root.mkdir()
    fake_stage = maps_root / f".w3xray-map-stage-{'c' * 32}"
    fake_stage.mkdir()
    (fake_stage / "payload.bin").write_bytes(b"user")
    forged = maps_root / f".w3xray-map-transaction-{'d' * 32}.json"
    forged.write_text("{}\n", encoding="utf-8")

    # When: recovery scans strict transaction names.
    diagnostics = publication_module.recover_map_publications(str(tmp_path))

    # Then: neither an unrecorded stage nor a malformed record is removed.
    assert fake_stage.is_dir()
    assert forged.is_file()
    assert tuple(item.code for item in diagnostics) == ("invalid_transaction",)


def test_discard_removes_only_its_matching_building_stage(tmp_path: Path) -> None:
    # Given: one recorded building stage and one unrelated private-looking path.
    staged = publication_module.create_map_stage(
        str(tmp_path),
        _RELATIVE,
        _DIGEST,
        transaction_id=_NEW_TRANSACTION,
    )
    fake = tmp_path / "地图" / f".w3xray-map-stage-{'c' * 32}"
    fake.mkdir()

    # When: the map processor abandons its building stage.
    diagnostics = publication_module.discard_map_stage(staged, str(tmp_path))

    # Then: only the exact recorded stage and record are removed.
    assert diagnostics == ()
    assert not staged.stage.exists()
    assert fake.exists()
    assert not tuple((tmp_path / "地图").glob("*.json"))


def _fingerprint() -> SourceFingerprint:
    return SourceFingerprint("/maps/sample.w3x", 3, 4, _DIGEST)


def _prepare_stage(
    output_root: Path,
    fingerprint: SourceFingerprint,
):
    staged = publication_module.create_map_stage(
        str(output_root),
        _RELATIVE,
        fingerprint.sha256,
        transaction_id=_NEW_TRANSACTION,
    )
    result = empty_result(fingerprint, _RELATIVE)
    finalized = write_empty_publication(
        staged.stage,
        result,
        staged.transaction_id,
    )
    return staged, finalized


def _inject_failure(
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
    failure_errno: int,
) -> Callable[[], None]:
    if phase in {"backup", "destination"}:
        original = publication_module._replace_directory
        target_call = 1 if phase == "backup" else 2
        calls = 0

        def replace_directory(source: Path, destination: Path) -> None:
            nonlocal calls
            calls += 1
            if calls == target_call:
                raise OSError(failure_errno, phase)
            original(source, destination)

        monkeypatch.setattr(publication_module, "_replace_directory", replace_directory)
        return lambda: monkeypatch.setattr(
            publication_module, "_replace_directory", original
        )
    if phase == "sync":
        original = publication_module._sync_map_root
        failed = False

        def sync_map_root(path: Path) -> None:
            nonlocal failed
            if not failed:
                failed = True
                raise OSError(failure_errno, phase)
            original(path)

        monkeypatch.setattr(publication_module, "_sync_map_root", sync_map_root)
        return lambda: monkeypatch.setattr(
            publication_module, "_sync_map_root", original
        )
    original_remove = publication_module._remove_owned_directory

    def remove_owned_directory(path: Path, digest: str) -> None:
        raise OSError(failure_errno, phase)

    monkeypatch.setattr(
        publication_module,
        "_remove_owned_directory",
        remove_owned_directory,
    )
    return lambda: monkeypatch.setattr(
        publication_module,
        "_remove_owned_directory",
        original_remove,
    )
