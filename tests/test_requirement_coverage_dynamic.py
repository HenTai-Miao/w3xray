"""Dynamic capability rows derived from the loaded map and selected sources."""

from __future__ import annotations

from w3xtool.api import MapData
from w3xtool.external_listfile import ExternalListfileReport
from w3xtool.knowledge_requirements import ExtractionCapabilities, format_requirement_coverage
from w3xtool.wtg_diagnostics import UnknownTriggerFunction
from w3xtool.wtg_models import TriggerHeader, TriggerTreeSummary


def test_requirement_coverage_uses_map_results() -> None:
    # Given: headers were parsed but ECA expansion lacks TriggerData.
    md = MapData(path="x.w3x", name="x")
    md.trigger_summary = _summary_with_missing_schema()

    # When: coverage is formatted without a readable game-data source.
    text = format_requirement_coverage(md, ExtractionCapabilities(game_data_kind="missing"))

    # Then: the matrix states actual partial/missing/static-only boundaries.
    assert "WTG ECA\t部分提取" in text
    assert "原生 CASC\t源数据缺失" in text
    assert "运行时解密\t不支持" in text


def test_requirement_coverage_reports_verified_listfile_outcomes() -> None:
    # Given: a listfile had confirmed, missing, unsafe, and duplicate entries.
    report = ExternalListfileReport(
        confirmed=("hidden/config.json",),
        missing=("ghost.blp",),
        unsafe=("../escape",),
        duplicates=("HIDDEN/CONFIG.JSON",),
    )
    capabilities = ExtractionCapabilities(external_listfile=report)

    # When: dynamic coverage is formatted.
    text = format_requirement_coverage(MapData(path="x.w3x", name="x"), capabilities)

    # Then: partial adoption and every result count are visible.
    assert "外部 listfile\t部分采用" in text
    assert "确认 1" in text
    assert "缺失 1" in text
    assert "不安全 1" in text
    assert "重复 1" in text


def test_requirement_coverage_no_argument_compatibility_keeps_request_rows() -> None:
    # Given/When: legacy callers request the generic matrix.
    text = format_requirement_coverage()

    # Then: existing user-requirement rows remain available.
    assert "提取/整理 UI 文本\t已覆盖（静态）" in text


def _summary_with_missing_schema() -> TriggerTreeSummary:
    return TriggerTreeSummary(
        version=7,
        is_reforged=False,
        category_count=0,
        variable_count=0,
        trigger_count=1,
        comment_count=0,
        script_count=0,
        categories=(),
        variables=(),
        triggers=(TriggerHeader("初始化", "", False, True, False, False, True, 0, 1),),
        missing_schema_functions=(UnknownTriggerFunction("初始化", "MissingAction", 2, 0x20),),
        has_unexpanded_functions=True,
    )

