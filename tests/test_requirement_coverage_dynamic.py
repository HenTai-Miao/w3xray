"""Dynamic capability rows derived from the loaded map and selected sources."""

from __future__ import annotations

from pathlib import Path

from w3xtool.api import MapData
from w3xtool.external_listfile import ExternalListfileReport
from w3xtool.knowledge_pack import write_knowledge_pack
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


def test_requirement_coverage_downgrades_fixed_rows_for_empty_map() -> None:
    # Given: a parsed MapData shell with no files, objects, scripts, or world data.
    md = MapData(path="missing.w3x", name="empty")

    # When: map-specific coverage is formatted.
    text = format_requirement_coverage(md)

    # Then: static catalog claims reflect missing artifacts instead of staying globally covered.
    assert "提取/整理 UI 文本\t未发现数据" in text
    assert "分析脚本条件分支\t未发现数据" in text
    assert "分析物品/技能/单位 ID\t未发现数据" in text


def test_requirement_coverage_derives_archive_diagnosis_from_map(tmp_path: Path) -> None:
    # Given: a map whose original archive is missing and no capabilities override.
    md = MapData(path=str(tmp_path / "missing.w3x"), name="missing")

    # When: coverage is formatted directly from the map.
    text = format_requirement_coverage(md)

    # Then: archive diagnosis and completeness report the same source failure.
    assert "归档诊断\t文件缺失" in text
    assert "核对提取是否完整\t部分覆盖（源不可读）" in text
    assert "归档诊断\t未运行" not in text


def test_requirement_coverage_consumes_archive_diagnosis_kind() -> None:
    # Given: a future archive-open diagnostic is supplied by the capability boundary.
    capabilities = ExtractionCapabilities(archive_diagnosis_kind="table_damage")

    # When: dynamic coverage is formatted.
    text = format_requirement_coverage(MapData(path="broken.w3x", name="broken"), capabilities)

    # Then: the diagnosis is visible rather than stored in an unused field.
    assert "归档诊断\t结构损坏" in text


def test_knowledge_pack_reports_missing_archive_diagnosis(tmp_path: Path) -> None:
    # Given: map data whose original archive no longer exists.
    md = MapData(path=str(tmp_path / "missing.w3x"), name="missing")
    out_dir = tmp_path / "pack"

    # When: the full knowledge pack is written.
    write_knowledge_pack(md, str(out_dir))

    # Then: the known source failure reaches coverage instead of reading as not run.
    completeness = (out_dir / "提取完整性.txt").read_text(encoding="utf-8")
    coverage = (out_dir / "需求覆盖.tsv").read_text(encoding="utf-8")
    assert "源状态：源文件不可读" in completeness
    assert "归档诊断\t文件缺失" in coverage


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
