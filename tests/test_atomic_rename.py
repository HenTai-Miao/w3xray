"""Platform contract tests for anchored no-replace directory rename."""

from __future__ import annotations

import os
import sys

import pytest

from gametool import atomic_rename
from gametool.atomic_rename import (
    AtomicRenameUnavailableError,
)


_REQUIRES_ATOMIC_DIRECTORY_RENAME = pytest.mark.skipif(
    not (sys.platform == "darwin" or sys.platform.startswith("linux")),
    reason="host has no supported atomic directory no-replace primitive",
)
_DIRECTORY_FLAGS = (
    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
)


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
