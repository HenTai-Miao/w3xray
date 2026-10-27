"""Descriptor capability, ancestry, and filename encoding boundaries."""

from __future__ import annotations

from pathlib import Path

import pytest

from gametool import integrity_path_binding as binding_api
from gametool.integrity_cli import run_integrity_cli


def _snapshot_argv(root: Path, output: Path) -> tuple[str, ...]:
    return ("snapshot", "--root", f"root={root}", "--output", str(output))


def _retained_argv(active: Path, output: Path) -> tuple[str, ...]:
    return (
        "retained-cache",
        "--active-root",
        str(active),
        "--output",
        str(output),
    )


def test_snapshot_fails_closed_when_path_binding_capabilities_are_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "payload").write_bytes(b"evidence")
    output = tmp_path / "snapshot.json"
    monkeypatch.setattr(binding_api, "_PATH_BINDING_AVAILABLE", False, raising=False)

    code = run_integrity_cli(_snapshot_argv(root, output))

    assert code == 2
    assert not output.exists()
