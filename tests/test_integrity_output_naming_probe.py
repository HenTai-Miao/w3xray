"""Ownership and recovery contracts for exact-parent naming probes."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from w3xtool import integrity_output_naming as naming_api


def test_probe_setup_collision_never_removes_unowned_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "a" * 32
    collision = tmp_path / f".w3xray-name-probe-{token}.tmp"
    collision.mkdir(mode=0o700)
    monkeypatch.setattr(naming_api.secrets, "token_hex", lambda _size: token)
    parent_descriptor = os.open(tmp_path, os.O_RDONLY)
    try:
        with pytest.raises(naming_api.IntegrityNamingProbeError):
            _ = naming_api.probe_filesystem_naming(parent_descriptor)
    finally:
        os.close(parent_descriptor)

    assert collision.is_dir()


def test_probe_cleanup_failure_reports_proved_nested_residue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_unlink = naming_api.os.unlink

    def fail_probe_leaf_unlink(
        name: str,
        *,
        dir_fd: int | None = None,
    ) -> None:
        if name.startswith(("Case-", "\u00e9-")):
            raise PermissionError("synthetic probe cleanup denial")
        original_unlink(name, dir_fd=dir_fd)

    monkeypatch.setattr(naming_api.os, "unlink", fail_probe_leaf_unlink)
    parent_descriptor = os.open(tmp_path, os.O_RDONLY)
    try:
        with pytest.raises(
            naming_api.IntegrityNamingProbeError,
            match=r"probe residue retained at \.w3xray-name-probe-.+/(?:Case|\u00e9)-",
        ):
            _ = naming_api.probe_filesystem_naming(parent_descriptor)
    finally:
        os.close(parent_descriptor)

    residues = tuple(tmp_path.glob(".w3xray-name-probe-*.tmp"))
    assert len(residues) == 1
    assert any(item.is_file() for item in residues[0].iterdir())
