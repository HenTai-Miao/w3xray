"""Identity races at private cleanup and restoration boundaries."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from w3xtool.safe_output_models import SafeWriteStatus
from w3xtool import safe_output_cleanup as cleanup_api
from w3xtool import safe_output_publication_identity as identity_api
from w3xtool import safe_output_publication_rollback as rollback_api


def _identity(path: Path) -> tuple[int, int]:
    details = path.stat(follow_symlinks=False)
    return details.st_dev, details.st_ino


def _payloads(parent: Path) -> set[bytes]:
    return {item.read_bytes() for item in parent.rglob("*") if item.is_file()}


def test_cleanup_claim_preserves_a_replacement_before_atomic_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owned = tmp_path / "owned"
    owned.write_bytes(b"owned")
    expected = _identity(owned)
    original_claim = identity_api.claim_name
    raced = False

    def replace_before_claim(
        parent_descriptor: int,
        source_name: str,
        claimed_name: str,
        claimed_identity: tuple[int, int],
        *,
        claimed_parent_descriptor: int | None = None,
    ) -> None:
        nonlocal raced
        if source_name == owned.name:
            owned.unlink()
            owned.write_bytes(b"concurrent")
            raced = True
        original_claim(
            parent_descriptor,
            source_name,
            claimed_name,
            claimed_identity,
            claimed_parent_descriptor=claimed_parent_descriptor,
        )

    monkeypatch.setattr(identity_api, "claim_name", replace_before_claim)
    parent_descriptor = os.open(tmp_path, os.O_RDONLY)
    try:
        cleanup_error = cleanup_api.remove_owned_name(
            parent_descriptor,
            owned.name,
            expected,
        )
    finally:
        os.close(parent_descriptor)

    assert raced
    assert cleanup_error is not None
    assert b"concurrent" in _payloads(tmp_path)


def test_cleanup_preserves_replacement_after_claim_before_unlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owned = tmp_path / "owned"
    owned.write_bytes(b"owned")
    expected = _identity(owned)
    original_identity = identity_api.object_identity
    raced = False

    def replace_after_claim_proof(
        parent_descriptor: int,
        name: str,
    ) -> tuple[int, int] | None:
        nonlocal raced
        observed = original_identity(parent_descriptor, name)
        if not raced and "w3xray-cleanup" in name and observed == expected:
            os.rename(
                name,
                "retained-owned",
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
            )
            replacement = os.open(
                name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=parent_descriptor,
            )
            try:
                _ = os.write(replacement, b"concurrent")
            finally:
                os.close(replacement)
            raced = True
        return observed

    monkeypatch.setattr(identity_api, "object_identity", replace_after_claim_proof)
    parent_descriptor = os.open(tmp_path, os.O_RDONLY)
    try:
        cleanup_error = cleanup_api.remove_owned_name(
            parent_descriptor,
            owned.name,
            expected,
        )
    finally:
        os.close(parent_descriptor)

    assert raced
    assert cleanup_error is not None
    assert b"concurrent" in _payloads(tmp_path)


def test_cleanup_unlink_failure_reports_proved_retained_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owned = tmp_path / "owned"
    owned.write_bytes(b"owned")
    expected = _identity(owned)
    original_unlink = identity_api.os.unlink

    def fail_owned_unlink(
        name: str,
        *,
        dir_fd: int | None = None,
    ) -> None:
        if "w3xray-cleanup" in name:
            raise PermissionError("synthetic cleanup denial")
        original_unlink(name, dir_fd=dir_fd)

    monkeypatch.setattr(identity_api.os, "unlink", fail_owned_unlink)
    parent_descriptor = os.open(tmp_path, os.O_RDONLY)
    try:
        cleanup_error = cleanup_api.remove_owned_name(
            parent_descriptor,
            owned.name,
            expected,
        )
    finally:
        os.close(parent_descriptor)

    retained = tuple(
        item
        for item in tmp_path.rglob("*")
        if item.is_file() and _identity(item) == expected
    )
    assert cleanup_error is not None
    assert len(retained) == 1
    relative = retained[0].relative_to(tmp_path).as_posix()
    assert f"retained at {relative}" in cleanup_error


def test_restore_carries_expected_identity_and_never_publishes_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backup = tmp_path / ".w3xray-backup-test.tmp"
    backup.write_bytes(b"previous")
    previous = _identity(backup)
    destination = tmp_path / "report.json"
    original_restore = rollback_api.restore_claim
    received_expectations: list[tuple[int, int] | None] = []

    def replace_before_restore(
        parent_descriptor: int,
        claimed_name: str,
        destination_name: str,
        expected: tuple[int, int] | None = None,
    ) -> str | None:
        received_expectations.append(expected)
        backup.unlink()
        backup.write_bytes(b"concurrent")
        assert expected is not None
        return original_restore(
            parent_descriptor,
            claimed_name,
            destination_name,
            expected,
        )

    monkeypatch.setattr(rollback_api, "restore_claim", replace_before_restore)
    parent_descriptor = os.open(tmp_path, os.O_RDONLY)
    try:
        reason = rollback_api.restore_previous(
            parent_descriptor,
            destination.name,
            backup.name,
            previous,
            "publication failed",
        )
    finally:
        os.close(parent_descriptor)

    assert received_expectations == [previous]
    assert "publication failed" in reason
    assert f"retained at {backup.name}" not in reason
    assert not destination.exists()
    assert b"concurrent" in _payloads(tmp_path)


def test_recovery_message_requires_reproved_previous_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "report.json"
    destination.write_bytes(b"concurrent destination")
    backup = tmp_path / ".w3xray-backup-test.tmp"
    backup.write_bytes(b"previous")
    previous = _identity(backup)
    staged = tmp_path / ".w3xray-stage-test.tmp"
    staged.write_bytes(b"staged")
    staged_identity = _identity(staged)
    original_identity = rollback_api.regular_identity
    raced = False

    def replace_backup_before_recovery_message(
        parent_descriptor: int,
        name: str,
    ) -> tuple[int, int] | None:
        nonlocal raced
        if name == destination.name and not raced:
            backup.unlink()
            backup.write_bytes(b"concurrent backup")
            raced = True
        return original_identity(parent_descriptor, name)

    monkeypatch.setattr(
        rollback_api,
        "regular_identity",
        replace_backup_before_recovery_message,
    )
    parent_descriptor = os.open(tmp_path, os.O_RDONLY)
    try:
        result = rollback_api.rollback_published(
            parent_descriptor,
            destination.name,
            staged_identity,
            backup.name,
            previous,
            str(destination),
            SafeWriteStatus.UNSAFE,
            "publication rejected",
        )
    finally:
        os.close(parent_descriptor)

    assert raced
    assert f"retained at {backup.name}" not in result.error
    assert destination.read_bytes() == b"concurrent destination"
    assert backup.read_bytes() == b"concurrent backup"
