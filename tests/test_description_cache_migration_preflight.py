"""Structural preflight tests for untrusted migration inputs and paths."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Literal, assert_never

import pytest

from tests.description_cache_conflict_fixture import write_conflicting_inputs
from tests.description_cache_migration_fixture import (
    LEGACY_RELATIVE,
    write_legacy_inputs,
)
from w3xtool import description_cache_migration as migration
from w3xtool.bounded_file import FileIdentity
from w3xtool.description_cache_migration import (
    DescriptionCacheMigrationError,
    DescriptionCacheMigrationOptions,
    migrate_description_cache,
)

type StructuralMutation = Literal["state_json", "cache_header", "report_header"]
type DuplicateIdentity = Literal["digest", "output", "path"]


@pytest.mark.parametrize("mutation", ("state_json", "cache_header", "report_header"))
def test_migration_fails_closed_on_malformed_structure(
    tmp_path: Path,
    mutation: StructuralMutation,
) -> None:
    # Given: one exact fixture has one structurally malformed authority file.
    legacy_output, legacy_cache = write_legacy_inputs(tmp_path)
    _break_structure(legacy_output, legacy_cache, mutation)
    output = tmp_path / "trusted"

    # When / Then: migration fails before creating any destination.
    with pytest.raises(DescriptionCacheMigrationError):
        migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, output)
        )
    assert not output.exists()


@pytest.mark.parametrize("identity", ("digest", "output", "path"))
def test_migration_rejects_duplicate_schema1_state_identity(
    tmp_path: Path,
    identity: DuplicateIdentity,
) -> None:
    # Given: two state results collide in exactly one authoritative identity.
    legacy_output, legacy_cache = write_conflicting_inputs(tmp_path)
    state = legacy_output / "批量提取状态.json"
    text = state.read_text(encoding="utf-8")
    match identity:
        case "digest":
            text = text.replace("b" * 64, "a" * 64)
        case "output":
            text = text.replace("地图/002_second_bbbbbbbb", "地图/001_first_aaaaaaaa")
        case "path":
            text = text.replace("/maps/second.w3x", "/maps/first.w3x")
        case unreachable:
            assert_never(unreachable)
    state.write_text(text, encoding="utf-8")
    output = tmp_path / "trusted"

    # When / Then
    with pytest.raises(DescriptionCacheMigrationError, match="duplicate"):
        migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, output)
        )
    assert not output.exists()


def test_migration_rejects_duplicate_json_object_keys(tmp_path: Path) -> None:
    # Given: a JSON object repeats a key that the default decoder would overwrite.
    legacy_output, legacy_cache = write_legacy_inputs(tmp_path)
    state = legacy_output / "批量提取状态.json"
    text = state.read_text(encoding="utf-8").replace(
        '"schema_version": 1',
        '"schema_version": 1, "schema_version": 1',
    )
    state.write_text(text, encoding="utf-8")
    output = tmp_path / "trusted"

    # When / Then
    with pytest.raises(DescriptionCacheMigrationError, match="duplicate JSON key"):
        migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, output)
        )
    assert not output.exists()


def test_migration_rejects_input_output_overlap_and_state_escape(
    tmp_path: Path,
) -> None:
    # Given: one destination overlaps input and a second state escapes its root.
    overlap_root = tmp_path / "overlap"
    legacy_output, legacy_cache = write_legacy_inputs(overlap_root)
    escape_root = tmp_path / "escape"
    escaped_output, escaped_cache = write_legacy_inputs(escape_root)
    state = escaped_output / "批量提取状态.json"
    state.write_text(
        state.read_text(encoding="utf-8").replace(LEGACY_RELATIVE, "../outside"),
        encoding="utf-8",
    )

    # When / Then
    with pytest.raises(DescriptionCacheMigrationError, match="overlap"):
        migrate_description_cache(
            DescriptionCacheMigrationOptions(
                legacy_output,
                legacy_cache,
                legacy_output / "nested",
            )
        )
    with pytest.raises(DescriptionCacheMigrationError, match="escapes"):
        migrate_description_cache(
            DescriptionCacheMigrationOptions(
                escaped_output,
                escaped_cache,
                tmp_path / "trusted",
            )
        )


def test_migration_rejects_symlinked_input_and_output_paths(tmp_path: Path) -> None:
    # Given: exact inputs are exposed through links and output itself is a link.
    legacy_output, legacy_cache = write_legacy_inputs(tmp_path / "real")
    linked_root = tmp_path / "linked-root"
    linked_root.symlink_to(legacy_output, target_is_directory=True)
    linked_cache = tmp_path / "linked-cache.tsv"
    linked_cache.symlink_to(legacy_cache)
    output_target = tmp_path / "output-target"
    output_target.mkdir()
    linked_output = tmp_path / "linked-output"
    linked_output.symlink_to(output_target, target_is_directory=True)

    # When / Then
    for options in (
        DescriptionCacheMigrationOptions(linked_root, legacy_cache, tmp_path / "a"),
        DescriptionCacheMigrationOptions(legacy_output, linked_cache, tmp_path / "b"),
        DescriptionCacheMigrationOptions(legacy_output, legacy_cache, linked_output),
    ):
        with pytest.raises(
            DescriptionCacheMigrationError,
            match="symlink|regular|unsafe",
        ):
            migrate_description_cache(options)


def test_migration_rejects_bytes_changing_between_stable_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the same file identity returns different bytes on its repeated read.
    legacy_output, legacy_cache = write_legacy_inputs(tmp_path)
    identity = FileIdentity(1, 2, 5)
    payloads: Iterator[bytes] = iter((b"first", b"other"))

    def unstable_read(
        _path: Path,
        _maximum: int,
        *,
        expected: FileIdentity | None = None,
    ) -> tuple[bytes, FileIdentity]:
        if expected is not None:
            assert expected == identity
        return next(payloads), identity

    monkeypatch.setattr(migration, "read_bounded_regular_file", unstable_read)
    output = tmp_path / "trusted"

    # When / Then
    with pytest.raises(DescriptionCacheMigrationError, match="changed while reading"):
        migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, output)
        )
    assert not output.exists()


def _break_structure(
    legacy_output: Path,
    legacy_cache: Path,
    mutation: StructuralMutation,
) -> None:
    match mutation:
        case "state_json":
            (legacy_output / "批量提取状态.json").write_text("{", encoding="utf-8")
        case "cache_header":
            legacy_cache.write_text("wrong\n", encoding="utf-8")
        case "report_header":
            (legacy_output / LEGACY_RELATIVE / "对象描述.tsv").write_text(
                "wrong\n",
                encoding="utf-8",
            )
        case unreachable:
            assert_never(unreachable)
