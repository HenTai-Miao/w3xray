"""Structural preflight tests for untrusted migration inputs and paths."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, assert_never

import pytest

from tests.description_cache_migration_fixture import (
    LEGACY_RELATIVE,
    write_legacy_inputs,
)
from tests.source_parent_swap_fixture import swapping_open
from gametool.description_cache_migration import (
    DescriptionCacheMigrationError,
    DescriptionCacheMigrationOptions,
    migrate_description_cache,
)

type StructuralMutation = Literal["state_json", "cache_header", "report_header"]
type DuplicateIdentity = Literal["digest", "output", "path"]


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


def test_migration_rejects_intermediate_source_parent_swapped_during_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the report's real parent is swapped through a symlink at open time.
    legacy_output, legacy_cache = write_legacy_inputs(tmp_path / "input")
    report = legacy_output / LEGACY_RELATIVE / "对象描述.tsv"
    source_parent = legacy_output / "地图"
    moved_parent = tmp_path / "moved-map-parent"
    events: list[str] = []
    monkeypatch.setattr(
        os,
        "open",
        swapping_open(os.open, source_parent, moved_parent, report, events),
    )
    output = tmp_path / "trusted"

    # When / Then: no intermediate symlink may be followed from the source root.
    with pytest.raises(DescriptionCacheMigrationError, match="source|symlink|stable"):
        _ = migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, output)
        )
    assert events == ["parent swapped"]
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
