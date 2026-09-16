"""Deterministic per-map and global batch report tests."""

from __future__ import annotations

import csv
from dataclasses import replace
import io

import pytest

from tests.batch_publication_fixture import empty_result
import w3xtool.batch_tsv as batch_tsv
from w3xtool.batch_descriptions import DescriptionRecord, DescriptionState
from w3xtool.batch_icon_export import (
    IconExportRecord,
    IconExportState,
    IconKind,
)
from w3xtool.batch_reports import (
    format_description_groups_tsv,
    format_description_tsv,
    format_icon_index_tsv,
    format_map_summary,
)
from w3xtool.batch_models import MapBatchState, SourceFingerprint
from w3xtool.batch_status import KnowledgeEvidence, KnowledgeGapReason
from w3xtool.icon_evidence_models import IconResolutionLayer
from w3xtool.icon_resources import IconObjectReference


def _description_record(
    *,
    raw_description: str = "|cffff0000说明|r|n第二行",
    readable_description: str = "说明\n第二行",
    state: DescriptionState = DescriptionState.MAP_VALUE,
) -> DescriptionRecord:
    return DescriptionRecord(
        category="技能",
        object_id="A001",
        base_id="AHbz",
        object_name="暴风雪",
        is_custom=True,
        level=1,
        raw_tip="提示",
        readable_tip="提示",
        tip_source="war3map.w3a",
        raw_description=raw_description,
        readable_description=readable_description,
        description_source="war3map.w3a",
        state=state,
    )


def _icon_record(
    *,
    state: IconExportState = IconExportState.COMPLETE,
) -> IconExportRecord:
    return IconExportRecord(
        kind=IconKind.NAMED,
        requested_path=r"Icons\BTN.blp",
        resolved_path=r"Icons\BTN.blp",
        source_path="War3Patch.mpq",
        block_index=None,
        sha256="b" * 64,
        original_relative_path="图标/原始/具名/Icons/BTN.blp",
        png_relative_path="图标/PNG/具名/Icons/BTN.png",
        original_written=True,
        png_written=state is IconExportState.COMPLETE,
        state=state,
        error="" if state is IconExportState.COMPLETE else "decode failed",
        objects=(IconObjectReference("技能", "A001", "暴风雪"),),
    )


def test_description_tsv_keeps_raw_and_readable_columns_separate() -> None:
    # Given
    record = _description_record()

    # When
    report = format_description_tsv((record,))

    # Then
    assert "原始说明\t可读说明\t说明来源\t完整性状态" in report
    row = next(csv.DictReader(io.StringIO(report), delimiter="\t"))
    assert row["原始说明"] == "|cffff0000说明|r|n第二行"
    assert row["可读说明"] == "说明\n第二行"


def test_description_groups_collapses_identical_rows_with_ids_and_levels() -> None:
    # Given: 三个对象共享同一提示与说明，等级分别为 1、1、2。
    base = _description_record()
    clone = replace(base, object_id="A002", level=2)

    # When
    report = format_description_groups_tsv((base, clone, replace(base)))

    # Then
    rows = list(csv.DictReader(io.StringIO(report), delimiter="\t"))
    assert len(rows) == 1
    row = rows[0]
    assert row["出现次数"] == "3"
    assert row["可读提示"] == "提示"
    assert row["可读说明"] == "说明\n第二行"
    assert row["对象ID"] == "A001 A002"
    assert row["等级"] == "1、2"
    assert row["完整性状态"] == DescriptionState.MAP_VALUE.value


def test_description_groups_sort_most_frequent_first_and_keep_state_split() -> None:
    # Given: 同文本存在两种完整性状态时按状态分开，出现多的组排在前面。
    rare = replace(
        _description_record(state=DescriptionState.CLIENT_FILL),
        readable_tip="补全提示",
        readable_description="补全说明",
    )
    frequent = replace(
        _description_record(),
        readable_tip="地图提示",
        readable_description="地图说明",
    )

    # When
    report = format_description_groups_tsv(
        (rare, frequent, replace(frequent), replace(frequent)),
    )

    # Then
    rows = list(csv.DictReader(io.StringIO(report), delimiter="\t"))
    assert [row["出现次数"] for row in rows] == ["3", "1"]
    assert rows[0]["可读提示"] == "地图提示"
    assert rows[1]["完整性状态"] == DescriptionState.CLIENT_FILL.value


def test_description_tsv_preserves_a_leading_quote_without_merging_columns() -> None:
    # Given
    text = '"烧伤附近的敌人。'
    record = _description_record(
        raw_description=text,
        readable_description=text,
    )

    # When
    report = format_description_tsv((record,))
    row = next(csv.DictReader(report.splitlines(), delimiter="\t"))

    # Then
    assert row["原始说明"] == text
    assert row["可读说明"] == text
    assert row["完整性状态"] == DescriptionState.MAP_VALUE.value


def test_description_tsv_round_trips_tabs_and_physical_newlines() -> None:
    # Given: legacy description output receives lossless raw evidence.
    text = '"开头\t字段\r\n第二行\n第三行'
    record = _description_record(
        raw_description=text,
        readable_description="开头\t字段\n第二行\n第三行",
    )

    # When: the report is parsed by the standard TSV reader.
    row = next(
        csv.DictReader(io.StringIO(format_description_tsv((record,))), delimiter="\t")
    )

    # Then: quoted TSV restores both versions exactly.
    assert row["原始说明"] == text
    assert row["可读说明"] == "开头\t字段\n第二行\n第三行"


@pytest.mark.parametrize(
    "payload",
    (
        '=HYPERLINK("https://example.invalid")',
        " \t@SUM(1,2)",
        "\u200e+1+1",
        "\n-cmd|calc",
    ),
)
def test_batch_tsv_neutralizes_formulas_with_reversible_lossless_encoding(
    payload: str,
) -> None:
    # Given: a map-controlled cell starts a spreadsheet formula after ignorable text.

    # When: the shared batch serializer emits the spreadsheet-facing TSV cell.
    report = batch_tsv.format_tsv_rows(((payload,),))
    encoded = next(csv.reader(io.StringIO(report), delimiter="\t"))[0]

    # Then: spreadsheet software sees text while trusted readers recover exact bytes.
    assert encoded != payload
    assert not encoded.lstrip().startswith(("=", "+", "-", "@"))
    assert batch_tsv.decode_tsv_cell(encoded) == payload


def test_icon_index_includes_true_source_and_all_object_references() -> None:
    # Given
    record = _icon_record()

    # When
    report = format_icon_index_tsv((record,))

    # Then
    assert "真实来源" in report
    assert "War3Patch.mpq" in report
    assert "技能:A001:暴风雪" in report


def test_icon_index_reports_the_exact_resolution_layer() -> None:
    # Given
    record = replace(
        _icon_record(),
        resolution_layer=IconResolutionLayer.CURRENT_MAP,
    )

    # When
    row = next(
        csv.DictReader(io.StringIO(format_icon_index_tsv((record,))), delimiter="\t")
    )

    # Then
    assert row["解析层"] == "current_map"


def test_map_summary_explains_source_coverage_partial_state() -> None:
    # Given: publication succeeded but no substantive source was available.
    result = replace(
        empty_result(
            SourceFingerprint("/maps/opaque.w3x", 3, 4, "a" * 64),
            "地图/001_opaque_aaaaaaaa",
        ),
        state=MapBatchState.PARTIAL,
        knowledge_evidence=KnowledgeEvidence.PARTIAL,
        knowledge_gap_reasons=(KnowledgeGapReason.SOURCE_COVERAGE_MISSING,),
        source_coverage_gap_count=1,
    )

    # When: the per-map human-readable summary is rendered.
    summary = format_map_summary(result)

    # Then: the user can see why zero extracted objects are not called complete.
    assert "发布结果：已发布" in summary
    assert "知识证据：部分" in summary
    assert "知识缺口：源覆盖缺失" in summary
    assert "源覆盖缺口：1" in summary
