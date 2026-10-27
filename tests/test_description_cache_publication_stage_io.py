"""Held-stage writer and whole-generation proof races."""

from __future__ import annotations

import importlib
import os
from typing import Never

import pytest

from gametool import description_cache_publication as publication
from gametool.description_cache_publication_errors import (
    DescriptionCachePublicationError,
)


_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)


def test_stage_io_support_preflight_rejects_incomplete_host_without_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stage_io = importlib.import_module(
        "gametool.description_cache_publication_stage_io"
    )
    calls = {"uuid4": 0, "rename_noreplace": 0, "rename_exchange": 0}

    def forbidden_uuid4() -> Never:
        calls["uuid4"] += 1
        raise AssertionError("stage-I/O preflight entered a transaction")

    def forbidden_noreplace(
        _parent_descriptor: int,
        _source_name: str,
        _destination_name: str,
    ) -> Never:
        calls["rename_noreplace"] += 1
        raise AssertionError("stage-I/O preflight called no-replace")

    def forbidden_exchange(
        _parent_descriptor: int,
        _source_name: str,
        _destination_name: str,
    ) -> Never:
        calls["rename_exchange"] += 1
        raise AssertionError("stage-I/O preflight called exchange")

    monkeypatch.setattr(stage_io, "_STAGE_IO_AVAILABLE", False)
    monkeypatch.setattr(publication, "uuid4", forbidden_uuid4)
    monkeypatch.setattr(publication, "_rename_noreplace", forbidden_noreplace)
    monkeypatch.setattr(publication, "_rename_exchange", forbidden_exchange)

    with pytest.raises(
        DescriptionCachePublicationError, match="stage I/O is unavailable"
    ):
        getattr(stage_io, "require_stage_io_support")()

    assert calls == dict.fromkeys(calls, 0)
