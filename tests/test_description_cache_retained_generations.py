"""End-to-end retained-generation publication outcomes."""

from __future__ import annotations

from collections.abc import Sequence
import importlib
from pathlib import Path
import sys
from typing import Never

import pytest

from gametool import description_cache_publication as publication
from gametool import description_cache_publication_stage as publication_stage
from gametool.atomic_rename import AtomicRenameUnavailableError
from gametool.description_cache_migration_models import (
    DescriptionCacheRejection,
    ProvenDescriptionCandidate,
)
from gametool.description_cache_publication import DescriptionCachePublicationError
from gametool.trusted_description_cache_models import TrustedCacheLeafProof


def _identity(path: Path) -> tuple[int, int]:
    details = path.stat(follow_symlinks=False)
    return details.st_dev, details.st_ino


def _transient_paths(output: Path) -> tuple[Path, ...]:
    return tuple(
        path
        for pattern in (
            ".gamexray-description-cache-stage-*",
            ".gamexray-description-cache-backup-*",
        )
        for path in output.parent.glob(pattern)
    )


def _retained_paths(output: Path) -> tuple[Path, ...]:
    return tuple(output.parent.glob(".gamexray-description-cache-retained-*-*"))


def _instrument_preflight_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, int]:
    calls: dict[str, int] = dict.fromkeys(
        ("uuid4", "mkdir", "writer", "rename_noreplace", "rename_exchange"),
        0,
    )

    def forbidden_uuid4() -> Never:
        calls["uuid4"] += 1
        raise AssertionError("UUID allocation ran before support preflight")

    def forbidden_mkdir(
        _name: str,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> Never:
        del mode, dir_fd
        calls["mkdir"] += 1
        raise AssertionError("stage mkdir ran before support preflight")

    def forbidden_writer(
        _source_root: Path,
        _stage_descriptor: int,
        _display_root: Path,
        _accepted: Sequence[ProvenDescriptionCandidate],
        _rejections: Sequence[DescriptionCacheRejection],
    ) -> tuple[TrustedCacheLeafProof, ...]:
        calls["writer"] += 1
        raise AssertionError("stage writer ran before support preflight")

    def forbidden_noreplace(
        _parent_descriptor: int,
        _source_name: str,
        _destination_name: str,
    ) -> Never:
        calls["rename_noreplace"] += 1
        raise AssertionError("no-replace ran before support preflight")

    def forbidden_exchange(
        _parent_descriptor: int,
        _source_name: str,
        _destination_name: str,
    ) -> Never:
        calls["rename_exchange"] += 1
        raise AssertionError("exchange ran before support preflight")

    monkeypatch.setattr(publication, "uuid4", forbidden_uuid4)
    monkeypatch.setattr(publication_stage.os, "mkdir", forbidden_mkdir)
    monkeypatch.setattr(
        publication,
        "build_description_cache_stage",
        forbidden_writer,
        raising=False,
    )
    monkeypatch.setattr(publication, "_rename_noreplace", forbidden_noreplace)
    monkeypatch.setattr(publication, "_rename_exchange", forbidden_exchange)
    return calls


def test_atomic_rename_unsupported_fails_before_any_publication_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy_output = tmp_path / "legacy"
    legacy_output.mkdir()
    output = tmp_path / "trusted"
    calls = _instrument_preflight_effects(monkeypatch)
    monkeypatch.setattr(sys, "platform", "unsupported")

    with pytest.raises(AtomicRenameUnavailableError):
        publication.publish_description_cache(legacy_output, output, (), ())

    assert calls == dict.fromkeys(calls, 0)
    assert (
        not output.exists()
        and not _transient_paths(output)
        and not _retained_paths(output)
    )


def test_stage_io_unsupported_fails_before_any_publication_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy_output = tmp_path / "legacy"
    legacy_output.mkdir()
    output = tmp_path / "trusted"
    stage_io = importlib.import_module(
        "gametool.description_cache_publication_stage_io"
    )
    calls = _instrument_preflight_effects(monkeypatch)
    atomic_preflight: list[str] = []
    monkeypatch.setattr(
        publication,
        "require_atomic_rename_support",
        lambda: atomic_preflight.append("confirmed-before-stage-io"),
    )
    monkeypatch.setattr(stage_io, "_STAGE_IO_AVAILABLE", False)

    with pytest.raises(
        DescriptionCachePublicationError, match="stage I/O is unavailable"
    ):
        publication.publish_description_cache(legacy_output, output, (), ())

    assert atomic_preflight == ["confirmed-before-stage-io"]
    assert calls == dict.fromkeys(calls, 0)
    assert (
        not output.exists()
        and not _transient_paths(output)
        and not _retained_paths(output)
    )
