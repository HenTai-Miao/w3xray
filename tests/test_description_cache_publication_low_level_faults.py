"""Exact low-level publication wrapper ledgers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, assert_never

import pytest

from tests.description_cache_publication_fixture import (
    assert_failure_order,
    open_parent,
    rename_in_parent,
)
from w3xtool import description_cache_publication_parent_identity as parent_identity
from w3xtool import description_cache_publication_stage as publication_stage
from w3xtool import description_cache_publication_stage_io as stage_io
from w3xtool.description_cache_owned_schema import TRUSTED_DESCRIPTION_CACHE_MARKER
from w3xtool.description_cache_publication_errors import (
    DescriptionCachePublicationError,
    PublicationCommitContextError,
)
from w3xtool.description_cache_publication_retention_names import RetainedCacheNames


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


def test_parent_descriptor_fstat_wrapper_ledgers_exact_fault(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fault = OSError("parent fstat")

    with open_parent(tmp_path) as descriptor:
        real_fstat = parent_identity.os.fstat

        def fail_fstat(current: int) -> os.stat_result:
            if current == descriptor:
                raise fault
            return real_fstat(current)

        monkeypatch.setattr(parent_identity.os, "fstat", fail_fstat)
        with pytest.raises(PublicationCommitContextError) as raised:
            _ = parent_identity.parent_descriptor_identity(descriptor)

    assert_failure_order(raised.value, (fault,))
    assert raised.value.__cause__ is fault


def test_public_parent_stat_wrapper_ledgers_exact_fault(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fault = OSError("public parent stat")
    expected = _identity(tmp_path)
    real_stat = parent_identity.os.stat

    def fail_stat(
        path: str | bytes | int | Path,
        *,
        dir_fd: int | None = None,
        follow_symlinks: bool = True,
    ) -> os.stat_result:
        if path == tmp_path:
            raise fault
        return real_stat(
            path,
            dir_fd=dir_fd,
            follow_symlinks=follow_symlinks,
        )

    monkeypatch.setattr(parent_identity.os, "stat", fail_stat)

    with open_parent(tmp_path) as descriptor:
        with pytest.raises(PublicationCommitContextError) as raised:
            parent_identity.require_parent_identity(
                descriptor,
                tmp_path,
                expected,
            )

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


@pytest.mark.parametrize("site", ("fstat", "public-stat"))
def test_stage_creation_initial_parent_fault_appears_once_first(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    site: CreationFaultSite,
) -> None:
    # Given: one initial parent proof syscall faults before mkdir.
    fault = OSError(f"initial {site}")
    match site:
        case "fstat":
            real_call = parent_identity.os.fstat
            calls = 0

            def fail_once(descriptor: int) -> os.stat_result:
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise fault
                return real_call(descriptor)

            monkeypatch.setattr(parent_identity.os, "fstat", fail_once)
        case "public-stat":
            real_stat = parent_identity.os.stat
            calls = 0

            def fail_once(
                path: str | bytes | int | Path,
                *,
                dir_fd: int | None = None,
                follow_symlinks: bool = True,
            ) -> os.stat_result:
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise fault
                return real_stat(
                    path,
                    dir_fd=dir_fd,
                    follow_symlinks=follow_symlinks,
                )

            monkeypatch.setattr(parent_identity.os, "stat", fail_once)
        case unreachable:
            assert_never(unreachable)

    # When: the complete creation boundary handles the typed low-level wrapper.
    with pytest.raises(PublicationCommitContextError) as raised:
        _ = publication_stage.create_stage_and_capture(
            tmp_path / "stage",
            tmp_path / "output",
            RetainedCacheNames(tmp_path, "2" * 32),
            rename_in_parent,
            os.fsync,
        )

    # Then: no aggregate duplicate precedes or replaces the exact syscall fault.
    assert_failure_order(raised.value, (fault,))
    assert raised.value.__cause__ is fault
    assert not (tmp_path / "stage").exists()


__all__: tuple[str, ...] = ()
