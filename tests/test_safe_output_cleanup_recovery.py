"""Truthful recovery paths for isolated safe-output cleanup namespaces."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from w3xtool import safe_output_cleanup as cleanup_api
from w3xtool import safe_output_cleanup_recovery as recovery_api
from w3xtool.safe_output_publication_states import (
    CleanupRetained,
    DisplacedAtBackup,
)


def _identity(path: Path) -> tuple[int, int]:
    details = path.stat(follow_symlinks=False)
    return details.st_dev, details.st_ino


def test_nested_recovery_path_requires_current_outer_and_inner_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backup = tmp_path / ".w3xray-backup-test.tmp"
    backup.write_bytes(b"previous")
    previous = _identity(backup)
    original_unlink = cleanup_api.os.unlink

    def fail_cleanup_unlink(
        name: str,
        *,
        dir_fd: int | None = None,
    ) -> None:
        if "w3xray-cleanup-owned" in name:
            raise PermissionError("synthetic cleanup denial")
        original_unlink(name, dir_fd=dir_fd)

    monkeypatch.setattr(cleanup_api.os, "unlink", fail_cleanup_unlink)
    parent_descriptor = os.open(tmp_path, os.O_RDONLY)
    try:
        outcome = cleanup_api.cleanup_owned_state(
            parent_descriptor,
            DisplacedAtBackup(backup.name, previous),
        )
        assert isinstance(outcome.state, CleanupRetained)
        retained = outcome.state
        owned_directory = tmp_path / "owned-cleanup-directory"
        (tmp_path / retained.directory_name).rename(owned_directory)
        replacement_directory = tmp_path / retained.directory_name
        replacement_directory.mkdir(mode=0o700)
        (replacement_directory / retained.leaf_name).write_bytes(b"concurrent")

        reason = recovery_api.retained_recovery_reason(
            parent_descriptor,
            retained,
            "publication failed",
        )
    finally:
        os.close(parent_descriptor)

    assert reason.endswith("recovery path unproved")
    assert f"retained at {retained.name}" not in reason
    assert (owned_directory / retained.leaf_name).read_bytes() == b"previous"
    assert (replacement_directory / retained.leaf_name).read_bytes() == b"concurrent"
