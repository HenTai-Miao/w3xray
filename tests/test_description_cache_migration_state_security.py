"""Authorization and identity tests for schema-1 migration state."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import pytest

from tests.description_cache_conflict_fixture import write_conflicting_inputs
from tests.description_cache_migration_fixture import write_legacy_inputs
from w3xtool.description_cache_migration import (
    DescriptionCacheMigrationError,
    DescriptionCacheMigrationOptions,
    migrate_description_cache,
)


type CasefoldIdentity = Literal["output", "path"]


@pytest.mark.parametrize(
    ("stage", "state"),
    (
        ("failed-but-has-output", "部分完成"),
        ("published", "not-a-schema1-state"),
        ("published", "失败"),
        ("Published", "完整"),
    ),
)
def test_migration_rejects_non_published_terminal_schema1_semantics(
    tmp_path: Path,
    stage: str,
    state: str,
) -> None:
    # Given: parseable schema-1 text does not describe a published success.
    legacy_output, legacy_cache = write_legacy_inputs(
        tmp_path,
        stage=stage,
        state=state,
    )
    output = tmp_path / "trusted"

    # When / Then
    with pytest.raises(DescriptionCacheMigrationError, match="published|state|stage"):
        _ = migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, output)
        )
    assert not output.exists()


@pytest.mark.parametrize(
    "alias",
    (
        "地图//001_fixture_aaaaaaaa",
        "地图/./001_fixture_aaaaaaaa",
        "地图\\001_fixture_aaaaaaaa",
        "地图/001_fixture_aaaaaaaa/",
    ),
)
def test_migration_rejects_noncanonical_schema1_output_directory(
    tmp_path: Path,
    alias: str,
) -> None:
    # Given: an output spelling normalizes to, or aliases, another report path.
    legacy_output, legacy_cache = write_legacy_inputs(
        tmp_path,
        state_output_directory=alias,
    )
    output = tmp_path / "trusted"

    # When / Then
    with pytest.raises(DescriptionCacheMigrationError, match="canonical|output"):
        _ = migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, output)
        )
    assert not output.exists()


@pytest.mark.parametrize("identity", ("output", "path"))
def test_migration_rejects_casefolded_schema1_identity_alias(
    tmp_path: Path,
    identity: CasefoldIdentity,
) -> None:
    # Given: two distinct strings have one canonical casefolded identity.
    legacy_output, legacy_cache = write_conflicting_inputs(tmp_path)
    state = legacy_output / "批量提取状态.json"
    text = state.read_text(encoding="utf-8")
    if identity == "output":
        text = text.replace(
            "地图/002_second_bbbbbbbb",
            "地图/001_FIRST_AAAAAAAA",
        )
    else:
        text = text.replace("/maps/second.w3x", "/MAPS/FIRST.W3X")
    _ = state.write_text(text, encoding="utf-8")
    output = tmp_path / "trusted"

    # When / Then
    with pytest.raises(DescriptionCacheMigrationError, match="duplicate"):
        _ = migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, output)
        )
    assert not output.exists()


def test_migration_rejects_distinct_outputs_bound_to_same_report_inode(
    tmp_path: Path,
) -> None:
    # Given: two canonical output names resolve to the same regular report inode.
    legacy_output, legacy_cache = write_conflicting_inputs(tmp_path)
    first = legacy_output / "地图/001_first_aaaaaaaa/对象描述.tsv"
    second = legacy_output / "地图/002_second_bbbbbbbb/对象描述.tsv"
    second.unlink()
    os.link(first, second)
    output = tmp_path / "trusted"

    # When / Then
    with pytest.raises(DescriptionCacheMigrationError, match="duplicate.*report"):
        _ = migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, output)
        )
    assert not output.exists()


@pytest.mark.parametrize("state", ("完整", "部分完成", "受限"))
def test_migration_accepts_exact_published_terminal_schema1_states(
    tmp_path: Path,
    state: str,
) -> None:
    # Given
    legacy_output, legacy_cache = write_legacy_inputs(tmp_path, state=state)
    output = tmp_path / "trusted"

    # When
    result = migrate_description_cache(
        DescriptionCacheMigrationOptions(legacy_output, legacy_cache, output)
    )

    # Then
    assert result.accepted_count == 1
