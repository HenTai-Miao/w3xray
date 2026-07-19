"""Continuous-name and crash-state guarantees for atomic replacement."""

from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

from w3xtool.safe_output import write_bytes_safely
from w3xtool.safe_output_models import SafeWriteStatus
from w3xtool.atomic_rename import rename_exchange as real_rename_exchange
from w3xtool import safe_output_publication as publication_api
from w3xtool import safe_output_publication_exchange_rollback as exchange_rollback_api
from w3xtool import safe_output_publication_existing as existing_api


class _SimulatedCrash(BaseException):
    """Stop the transaction without running an ordinary error rollback."""


def _create_regular(parent_descriptor: int, name: str, payload: bytes) -> None:
    descriptor = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
        dir_fd=parent_descriptor,
    )
    try:
        _ = os.write(descriptor, payload)
    finally:
        os.close(descriptor)


def test_existing_public_name_is_present_at_every_directory_sync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "report.json"
    destination.write_bytes(b"previous")
    observations: list[bytes] = []
    original_sync = publication_api.sync_directory_descriptor

    def observe_public_name(parent_descriptor: int) -> None:
        assert destination.exists()
        observations.append(destination.read_bytes())
        original_sync(parent_descriptor)

    monkeypatch.setattr(
        publication_api,
        "sync_directory_descriptor",
        observe_public_name,
    )

    result = write_bytes_safely(str(tmp_path), destination.name, b"replacement")

    assert result.status is SafeWriteStatus.WRITTEN
    assert observations
    assert destination.read_bytes() == b"replacement"


def test_crash_at_first_directory_sync_never_leaves_public_name_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "report.json"
    destination.write_bytes(b"previous")

    def crash(_parent_descriptor: int) -> None:
        raise _SimulatedCrash

    monkeypatch.setattr(publication_api, "sync_directory_descriptor", crash)

    with pytest.raises(_SimulatedCrash):
        _ = write_bytes_safely(str(tmp_path), destination.name, b"replacement")

    assert destination.exists()
    assert destination.read_bytes() in {b"previous", b"replacement"}


def test_destination_replacement_between_precheck_and_exchange_is_restored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "report.json"
    destination.write_bytes(b"previous")
    raced = False

    def replace_before_exchange(
        source_parent_descriptor: int,
        source_name: str,
        destination_parent_descriptor: int,
        destination_name: str,
    ) -> None:
        nonlocal raced
        if not raced:
            os.rename(
                destination_name,
                "previous-retained",
                src_dir_fd=destination_parent_descriptor,
                dst_dir_fd=destination_parent_descriptor,
            )
            _create_regular(
                destination_parent_descriptor,
                destination_name,
                b"concurrent",
            )
            raced = True
        real_rename_exchange(
            source_parent_descriptor,
            source_name,
            destination_parent_descriptor,
            destination_name,
        )

    monkeypatch.setattr(existing_api, "rename_exchange", replace_before_exchange)

    result = write_bytes_safely(str(tmp_path), destination.name, b"replacement")

    assert raced
    assert result.status is SafeWriteStatus.UNSAFE
    assert destination.read_bytes() == b"concurrent"
    assert (tmp_path / "previous-retained").read_bytes() == b"previous"


def test_backup_claim_failure_rolls_back_from_displaced_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "report.json"
    destination.write_bytes(b"previous")

    def fail_before_backup_exists(
        _parent_descriptor: int,
        _displaced: object,
        _backup_name: str,
    ) -> object:
        raise FileExistsError(errno.EEXIST, "synthetic backup collision")

    monkeypatch.setattr(
        existing_api,
        "claim_displaced_previous",
        fail_before_backup_exists,
    )

    result = write_bytes_safely(str(tmp_path), destination.name, b"replacement")

    assert result.status is SafeWriteStatus.UNSAFE
    assert destination.read_bytes() == b"previous"
    assert not tuple(tmp_path.glob(".w3xray-backup-*.tmp"))


def test_destination_replacement_between_rollback_proof_and_exchange_is_restored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "report.json"
    destination.write_bytes(b"previous")
    raced = False

    def fail_sync(_parent_descriptor: int) -> None:
        raise OSError("synthetic publication sync failure")

    def replace_before_rollback_exchange(
        source_parent_descriptor: int,
        source_name: str,
        destination_parent_descriptor: int,
        destination_name: str,
    ) -> None:
        nonlocal raced
        if not raced:
            os.rename(
                destination_name,
                "replacement-retained",
                src_dir_fd=destination_parent_descriptor,
                dst_dir_fd=destination_parent_descriptor,
            )
            _create_regular(
                destination_parent_descriptor,
                destination_name,
                b"concurrent",
            )
            raced = True
        real_rename_exchange(
            source_parent_descriptor,
            source_name,
            destination_parent_descriptor,
            destination_name,
        )

    monkeypatch.setattr(publication_api, "sync_directory_descriptor", fail_sync)
    monkeypatch.setattr(
        exchange_rollback_api,
        "rename_exchange",
        replace_before_rollback_exchange,
    )

    result = write_bytes_safely(str(tmp_path), destination.name, b"replacement")

    assert raced
    assert result.status is SafeWriteStatus.FAILED
    assert destination.read_bytes() == b"concurrent"
    assert (tmp_path / "replacement-retained").read_bytes() == b"replacement"
    assert b"previous" in {
        item.read_bytes() for item in tmp_path.rglob("*") if item.is_file()
    }
