"""Exact low-level publication wrapper ledgers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import pytest

from tests.description_cache_publication_fixture import (
    assert_failure_order,
    rename_in_parent,
)
from gametool import description_cache_publication_stage as publication_stage
from gametool import description_cache_publication_stage_io as stage_io
from gametool.description_cache_owned_schema import TRUSTED_DESCRIPTION_CACHE_MARKER
from gametool.description_cache_publication_errors import (
    DescriptionCachePublicationError,
    PublicationCommitContextError,
)
from gametool.description_cache_publication_retention_names import RetainedCacheNames


type CreationFaultSite = Literal["fstat", "public-stat"]


def _identity(path: Path) -> tuple[int, int]:
    details = path.stat(follow_symlinks=False)
    return details.st_dev, details.st_ino


def test_initial_publication_parent_open_wrapper_ledgers_exact_fault(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the very first no-follow parent open fails.
    fault = OSError("parent open")

    def fail_open(*_args: str | int | Path, **_kwargs: int) -> int:
        raise fault

    monkeypatch.setattr(publication_stage.os, "open", fail_open)

    # When: stage creation tries to bind its publication parent.
    with pytest.raises(PublicationCommitContextError) as raised:
        _ = publication_stage.create_stage_and_capture(
            tmp_path / "stage",
            tmp_path / "output",
            RetainedCacheNames(tmp_path, "1" * 32),
            rename_in_parent,
            os.fsync,
        )

    # Then: the exact syscall fault is first and remains the explicit cause.
    assert_failure_order(raised.value, (fault,))
    assert raised.value.__cause__ is fault


def test_stage_writer_leaf_open_wrapper_ledgers_exact_fault(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fault = OSError("stage writer open")

    def fail_open(*_args: str | int | Path, **_kwargs: int) -> int:
        raise fault

    monkeypatch.setattr(stage_io.os, "open", fail_open)

    with pytest.raises(DescriptionCachePublicationError) as raised:
        _ = stage_io.write_stage_text(
            101,
            tmp_path,
            TRUSTED_DESCRIPTION_CACHE_MARKER,
            "payload",
        )

    assert_failure_order(raised.value, (fault,))
    assert raised.value.__cause__ is fault


__all__: tuple[str, ...] = ()
