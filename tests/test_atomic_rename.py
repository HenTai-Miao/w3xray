"""Platform contract tests for anchored no-replace directory rename."""

from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest

from w3xtool.atomic_rename import rename_noreplace


pytestmark = pytest.mark.skipif(
    not (sys.platform == "darwin" or sys.platform.startswith("linux")),
    reason="host has no supported atomic directory no-replace primitive",
)
_DIRECTORY_FLAGS = (
    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
)


def test_atomic_rename_moves_directory_to_absent_anchored_name(
    tmp_path: Path,
) -> None:
    # Given
    source = tmp_path / "source"
    source.mkdir()
    _ = (source / "sentinel").write_text("source", encoding="utf-8")
    parent_descriptor = os.open(tmp_path, _DIRECTORY_FLAGS)

    # When
    try:
        rename_noreplace(parent_descriptor, "source", parent_descriptor, "target")
    finally:
        os.close(parent_descriptor)

    # Then
    assert not source.exists()
    assert (tmp_path / "target" / "sentinel").read_text(encoding="utf-8") == "source"


def test_atomic_rename_never_replaces_existing_anchored_directory(
    tmp_path: Path,
) -> None:
    # Given
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    _ = (source / "sentinel").write_text("source", encoding="utf-8")
    _ = (target / "sentinel").write_text("target", encoding="utf-8")
    before = os.stat(target, follow_symlinks=False)
    parent_descriptor = os.open(tmp_path, _DIRECTORY_FLAGS)

    # When / Then
    try:
        with pytest.raises(FileExistsError):
            rename_noreplace(
                parent_descriptor,
                "source",
                parent_descriptor,
                "target",
            )
    finally:
        os.close(parent_descriptor)
    after = os.stat(target, follow_symlinks=False)
    assert (after.st_dev, after.st_ino) == (before.st_dev, before.st_ino)
    assert (source / "sentinel").read_text(encoding="utf-8") == "source"
    assert (target / "sentinel").read_text(encoding="utf-8") == "target"
