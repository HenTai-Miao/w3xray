"""Platform contract tests for anchored no-replace directory rename."""

from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest

from w3xtool import atomic_rename
from w3xtool.atomic_rename import (
    AtomicRenameUnavailableError,
    rename_noreplace,
)


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


def test_atomic_exchange_swaps_two_anchored_directories_without_absence(
    tmp_path: Path,
) -> None:
    # Given: both exchange names exist below one held parent descriptor.
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    _ = (source / "sentinel").write_text("source", encoding="utf-8")
    _ = (target / "sentinel").write_text("target", encoding="utf-8")
    parent_descriptor = os.open(tmp_path, _DIRECTORY_FLAGS)

    # When
    try:
        atomic_rename.rename_exchange(
            parent_descriptor,
            "source",
            parent_descriptor,
            "target",
        )
        both_names_present = source.is_dir() and target.is_dir()
    finally:
        os.close(parent_descriptor)

    # Then
    assert both_names_present
    assert (source / "sentinel").read_text(encoding="utf-8") == "target"
    assert (target / "sentinel").read_text(encoding="utf-8") == "source"


@pytest.mark.parametrize(
    ("platform", "symbol"),
    (("darwin", "renameatx_np"), ("linux", "renameat2")),
)
def test_atomic_exchange_selects_platform_swap_primitive(
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    symbol: str,
) -> None:
    # Given
    calls: list[tuple[str, int]] = []

    def record_call(
        selected_symbol: str,
        _source_descriptor: int,
        _source_name: str,
        _destination_descriptor: int,
        _destination_name: str,
        flags: int,
    ) -> None:
        calls.append((selected_symbol, flags))

    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(atomic_rename, "_call", record_call)

    # When
    atomic_rename.rename_exchange(3, "source", 4, "target")

    # Then: both Darwin and Linux use their atomic swap flag, never replace.
    assert calls == [(symbol, 2)]


def test_atomic_exchange_fails_closed_on_unsupported_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    monkeypatch.setattr(sys, "platform", "unsupported")

    # When / Then
    with pytest.raises(AtomicRenameUnavailableError, match="unavailable"):
        atomic_rename.rename_exchange(3, "source", 4, "target")


def test_atomic_rename_support_preflight_rejects_unsupported_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter_calls: list[None] = []

    def forbidden_call(
        _symbol: str,
        _source_descriptor: int,
        _source_name: str,
        _destination_descriptor: int,
        _destination_name: str,
        _flags: int,
    ) -> None:
        adapter_calls.append(None)

    monkeypatch.setattr(sys, "platform", "unsupported")
    monkeypatch.setattr(atomic_rename, "_call", forbidden_call)

    with pytest.raises(AtomicRenameUnavailableError):
        getattr(atomic_rename, "require_atomic_rename_support")()

    assert adapter_calls == []
