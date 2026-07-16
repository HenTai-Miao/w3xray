"""Fail-closed migration tests for historical description evidence."""

from __future__ import annotations

import importlib.util
from collections.abc import Iterator
from collections.abc import Iterable
from contextlib import contextmanager
from importlib import import_module
from pathlib import Path

import pytest

from tests.description_cache_migration_fixture import (
    CandidateMutation,
    LEGACY_RELATIVE,
    candidate,
    legacy_client_fill,
    write_legacy_inputs,
    write_mutated_inputs,
)
from tests.description_cache_conflict_fixture import write_conflicting_inputs
from w3xtool import description_cache_migration_rows as migration_rows
from w3xtool.description_cache import load_description_cache
from w3xtool.description_cache_migration import (
    DescriptionCacheMigrationError,
    DescriptionCacheMigrationOptions,
    migrate_description_cache,
)


_LEGACY_CACHE_HEADER = (
    "分类",
    "基础ID",
    "文本角色",
    "等级/变体",
    "原始全文",
    "可读全文",
    "来源地图SHA256",
    "来源路径",
)
_LEGACY_DESCRIPTION_HEADER = (
    "分类",
    "对象ID",
    "基础ID",
    "名称",
    "自定义",
    "等级",
    "原始提示",
    "可读提示",
    "提示来源",
    "原始说明",
    "可读说明",
    "说明来源",
    "完整性状态",
)


def test_migration_boundary_exists_when_task5_is_enabled() -> None:
    # Given: the repository is at the pre-Task-5 cache implementation.
    module_name = "w3xtool.description_cache_migration"

    # When: the explicit migration boundary is discovered.
    specification = importlib.util.find_spec(module_name)

    # Then: Task 5 provides a dedicated boundary instead of implicit harvesting.
    assert specification is not None


def test_migration_boundary_exposes_typed_contracts() -> None:
    # Given: the dedicated migration module can be imported.
    module = import_module("w3xtool.description_cache_migration")

    # When: its public Task 5 contracts are inspected.
    names = (
        "DescriptionCacheMigrationError",
        "DescriptionCacheMigrationOptions",
        "DescriptionCacheMigrationResult",
        "DescriptionCacheRejection",
        "DescriptionCacheRejectionReason",
        "migrate_description_cache",
    )

    # Then: every migration boundary contract is explicit and typed by name.
    assert all(hasattr(module, name) for name in names)


def test_legacy_headers_are_exact_when_parsing_historical_evidence() -> None:
    # Given: the current cache schema deliberately differs from schema 2.
    schema = import_module("w3xtool.description_cache_schema")

    # When: the two historical headers are selected explicitly.
    cache_header = getattr(schema, "LEGACY_CACHE_HEADER", None)
    description_header = getattr(schema, "LEGACY_DESCRIPTION_HEADER", None)

    # Then: column names and ordering match the historical files byte-for-byte.
    assert cache_header == _LEGACY_CACHE_HEADER
    assert description_header == _LEGACY_DESCRIPTION_HEADER


def test_migration_accepts_only_exact_base_client_fill(tmp_path: Path) -> None:
    # Given: schema-1 state, schema-2 cache, and its exact base-client source row.
    legacy_output, legacy_cache = write_legacy_inputs(tmp_path)
    output = tmp_path / "trusted"

    # When: the explicit migration proves and publishes the candidate.
    result = migrate_description_cache(
        DescriptionCacheMigrationOptions(legacy_output, legacy_cache, output)
    )

    # Then: exactly one manifest-bound base description is available.
    assert result.accepted_count == 1
    assert result.rejected_count == 0
    cache = load_description_cache(str(output / "可信描述缓存.tsv"))
    assert cache.lookup("物品", "ratf", "扩展提示", None)[0].raw_value == "原版说明"


@pytest.mark.parametrize(
    ("mutation", "reason"),
    (
        ("custom_object", "not_base_object"),
        ("source_digest", "source_map_unknown"),
        ("source_label", "source_label_mismatch"),
        ("readable", "readable_mismatch"),
        ("report_value", "source_row_missing"),
    ),
)
def test_migration_rejects_unproved_rows(
    tmp_path: Path,
    mutation: CandidateMutation,
    reason: str,
) -> None:
    # Given: one structurally valid legacy row has one named semantic proof gap.
    legacy_output, legacy_cache = write_mutated_inputs(tmp_path, mutation)

    # When: migration evaluates the candidate without aborting the valid structure.
    result = migrate_description_cache(
        DescriptionCacheMigrationOptions(
            legacy_output,
            legacy_cache,
            tmp_path / "trusted",
        )
    )

    # Then: that row is rejected for the stable, specific reason.
    assert result.accepted_count == 0
    assert result.rejected_count == 1
    assert result.rejections[0].reason.value == reason


@pytest.mark.parametrize(
    ("cache_row", "report_row", "reason"),
    (
        (
            candidate(level="01"),
            legacy_client_fill(level="01"),
            "invalid_identity",
        ),
        (
            candidate(role="编辑器描述"),
            legacy_client_fill(),
            "unsupported_role",
        ),
    ),
)
def test_migration_rejects_invalid_identity_before_source_checks(
    tmp_path: Path,
    cache_row: tuple[str, ...],
    report_row: tuple[str, ...],
    reason: str,
) -> None:
    # Given: the base exists, while level or role syntax cannot identify a legacy field.
    legacy_output, legacy_cache = write_legacy_inputs(
        tmp_path,
        cache_rows=(cache_row,),
        report_rows=(report_row,),
    )

    # When
    result = migrate_description_cache(
        DescriptionCacheMigrationOptions(legacy_output, legacy_cache, tmp_path / "out")
    )

    # Then
    assert result.rejections[0].reason.value == reason


def test_migration_distinguishes_source_path_escape_and_missing_report(
    tmp_path: Path,
) -> None:
    # Given: one candidate points outside its state path and one exact report vanished.
    escaped_root = tmp_path / "escaped"
    escaped_output, escaped_cache = write_legacy_inputs(
        escaped_root,
        source_paths=(f"{tmp_path / 'outside.tsv'}#base:ratf",),
    )
    missing_root = tmp_path / "missing"
    missing_output, missing_cache = write_legacy_inputs(missing_root)
    (missing_output / LEGACY_RELATIVE / "对象描述.tsv").unlink()

    # When
    escaped = migrate_description_cache(
        DescriptionCacheMigrationOptions(escaped_output, escaped_cache, tmp_path / "a")
    )
    missing = migrate_description_cache(
        DescriptionCacheMigrationOptions(missing_output, missing_cache, tmp_path / "b")
    )

    # Then
    assert escaped.rejections[0].reason.value == "source_path_escape"
    assert missing.rejections[0].reason.value == "source_report_missing"


def test_migration_rejects_candidate_when_tsv_round_trip_is_not_exact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: exact legacy evidence but a serialization boundary that loses its cells.
    legacy_output, legacy_cache = write_legacy_inputs(tmp_path)
    monkeypatch.setattr(migration_rows, "format_tsv_rows", _broken_tsv)

    # When
    result = migrate_description_cache(
        DescriptionCacheMigrationOptions(legacy_output, legacy_cache, tmp_path / "out")
    )

    # Then
    assert result.rejections[0].reason.value == "tsv_round_trip_mismatch"


def test_migration_rejects_every_member_of_a_conflicting_value_group(
    tmp_path: Path,
) -> None:
    # Given: two independently proven source maps disagree on one exact five-tuple.
    legacy_output, legacy_cache = write_conflicting_inputs(tmp_path)

    # When
    result = migrate_description_cache(
        DescriptionCacheMigrationOptions(legacy_output, legacy_cache, tmp_path / "out")
    )

    # Then: neither value survives and both candidates have stable conflict rows.
    assert result.accepted_count == 0
    assert result.rejected_count == 2
    assert {row.reason.value for row in result.rejections} == {"conflicting_value"}


def _broken_tsv(_rows: Iterable[tuple[str, ...]]) -> str:
    return "broken\n"


def test_migration_error_propagates_through_context_manager() -> None:
    # Given: Python's context-manager protocol may assign exception traceback state.
    @contextmanager
    def boundary() -> Iterator[None]:
        yield

    # When / Then: the typed migration error propagates without being masked.
    with pytest.raises(DescriptionCacheMigrationError, match="fixture failure"):
        with boundary():
            raise DescriptionCacheMigrationError("fixture failure")
