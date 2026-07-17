"""Held-stage writer and whole-generation proof races."""

from __future__ import annotations

from collections.abc import Sequence
import importlib
import os
from pathlib import Path
from typing import Never

import pytest

from tests.description_cache_publication_fixture import replacement_inputs
from tests.trusted_description_cache_fixture import published_cache
from w3xtool import description_cache_publication as publication
from w3xtool.description_cache_migration import (
    DescriptionCacheMigrationOptions,
    migrate_description_cache,
)
from w3xtool.description_cache_migration_models import (
    DescriptionCacheRejection,
    ProvenDescriptionCandidate,
)
from w3xtool.description_cache_publication_errors import (
    DescriptionCachePublicationError,
)
from w3xtool.trusted_description_cache_models import (
    TrustedCacheLeafProof,
    VerifiedDescriptionCacheGeneration,
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
    stage_io = importlib.import_module("w3xtool.description_cache_publication_stage_io")
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


def test_writer_return_leaf_replacement_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stage_io = importlib.import_module("w3xtool.description_cache_publication_stage_io")
    stage = tmp_path / "stage"
    stage.mkdir()
    descriptor = os.open(stage, _DIRECTORY_FLAGS)
    target = stage / "可信描述缓存.tsv"
    displaced = tmp_path / "written-original"
    real_write = getattr(stage_io, "write_chunks_to_descriptor")

    def replace_after_write(file_descriptor: int, chunks: tuple[bytes, ...]) -> int:
        size = real_write(file_descriptor, chunks)
        target.rename(displaced)
        target.write_bytes(b"foreign")
        return size

    monkeypatch.setattr(stage_io, "write_chunks_to_descriptor", replace_after_write)
    try:
        with pytest.raises(DescriptionCachePublicationError, match="changed"):
            getattr(stage_io, "write_stage_text")(
                descriptor,
                stage,
                target.name,
                "expected",
            )
    finally:
        os.close(descriptor)

    assert target.read_bytes() == b"foreign"
    assert displaced.read_text(encoding="utf-8") == "expected"


def test_whole_stage_replacement_after_validation_is_rejected_before_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "first")
    output = tmp_path / "trusted"
    substitute = published_cache(tmp_path / "substitute", raw="foreign")
    displaced = tmp_path / "held-generation"
    displaced.mkdir()
    original = getattr(publication, "load_trusted_description_cache_from_descriptor")
    swapped = False
    rename_calls = 0
    real_rename = getattr(publication, "_rename_noreplace")

    def validate_then_swap(
        descriptor: int,
        display_root: Path,
        leaves: tuple[TrustedCacheLeafProof, ...],
    ) -> VerifiedDescriptionCacheGeneration:
        nonlocal swapped
        generation = original(descriptor, display_root, leaves)
        if not swapped:
            swapped = True
            substitute_descriptor = os.open(substitute, _DIRECTORY_FLAGS)
            displaced_descriptor = os.open(displaced, _DIRECTORY_FLAGS)
            try:
                for name in os.listdir(descriptor):
                    os.rename(
                        name,
                        name,
                        src_dir_fd=descriptor,
                        dst_dir_fd=displaced_descriptor,
                    )
                for name in os.listdir(substitute_descriptor):
                    os.rename(
                        name,
                        name,
                        src_dir_fd=substitute_descriptor,
                        dst_dir_fd=descriptor,
                    )
            finally:
                os.close(displaced_descriptor)
                os.close(substitute_descriptor)
        return generation

    def count_rename(descriptor: int, source: str, target: str) -> None:
        nonlocal rename_calls
        if target == output.name:
            rename_calls += 1
        real_rename(descriptor, source, target)

    monkeypatch.setattr(
        publication,
        "load_trusted_description_cache_from_descriptor",
        validate_then_swap,
    )
    monkeypatch.setattr(publication, "_rename_noreplace", count_rename)
    with pytest.raises(DescriptionCachePublicationError):
        migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, output)
        )

    assert swapped and rename_calls == 0 and not output.exists()


def test_generation_snapshot_rejects_early_same_size_in_place_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generation_io = importlib.import_module(
        "w3xtool.trusted_description_cache_generation_io"
    )
    root = published_cache(tmp_path / "cache", raw="first")
    descriptor = os.open(root, _DIRECTORY_FLAGS)
    original = getattr(generation_io, "read_owned_regular_file")
    calls = 0

    def mutate_after_first(
        parent_descriptor: int,
        name: str,
        named: os.stat_result,
        root: Path,
        maximum: int,
    ) -> bytes:
        nonlocal calls
        payload = original(parent_descriptor, name, named, root, maximum)
        calls += 1
        if calls == 1:
            path = root / name
            data = path.read_bytes()
            path.write_bytes(bytes((byte ^ 1 for byte in data)))
        return payload

    monkeypatch.setattr(generation_io, "read_owned_regular_file", mutate_after_first)
    try:
        with pytest.raises(Exception, match="changed|proof|stable"):
            getattr(generation_io, "read_trusted_cache_from_descriptor")(
                descriptor,
                root,
            )
    finally:
        os.close(descriptor)


def test_stage_leaf_takeover_after_capture_never_receives_writer_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "first")
    output = tmp_path / "trusted"
    original = getattr(publication, "build_description_cache_stage")
    displaced = tmp_path / "captured-stage"
    foreign_bytes = b"foreign sentinel"

    def takeover_then_build(
        source_root: Path,
        stage_descriptor: int,
        display_root: Path,
        accepted: Sequence[ProvenDescriptionCandidate],
        rejections: Sequence[DescriptionCacheRejection],
    ) -> tuple[TrustedCacheLeafProof, ...]:
        display_root.rename(displaced)
        display_root.mkdir()
        (display_root / "sentinel").write_bytes(foreign_bytes)
        return original(
            source_root,
            stage_descriptor,
            display_root,
            accepted,
            rejections,
        )

    monkeypatch.setattr(
        publication, "build_description_cache_stage", takeover_then_build
    )
    with pytest.raises(DescriptionCachePublicationError):
        migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, output)
        )

    sentinels = tuple(output.parent.glob(".w3xray-description-cache-*/sentinel"))
    assert len(sentinels) == 1 and sentinels[0].read_bytes() == foreign_bytes
    assert {path.name for path in sentinels[0].parent.iterdir()} == {"sentinel"}
